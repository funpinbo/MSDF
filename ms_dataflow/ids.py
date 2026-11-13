"""ID 계산. Planner와 Resolver가 반드시 같은 값을 내야 하므로 해시는 전부 여기에만 둔다.

- step_key: 생산 단계 하나의 정체 (서비스, Action, 버전, 슬롯별 입력, 루트 params)
- lineage_key: 출력 슬롯 하나의 정체 = step_key + 출력 슬롯 이름. "요청의 정체"
- artifact_id: 저장된 데이터의 정체 = 부모 artifact_id + lineage_key + generation
"""

from __future__ import annotations

import ast
import hashlib
import json
import textwrap
from collections.abc import Iterable, Mapping
from typing import Any

_SEP = "\x1f"


def canonical_json(value: Any) -> str:
    """키 순서와 공백에 영향받지 않는 JSON 문자열."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(kind: str, *parts: str) -> str:
    h = hashlib.sha256(kind.encode())
    for p in parts:
        h.update(_SEP.encode())
        h.update(p.encode())
    return h.hexdigest()[:32]


def step_key(
    service: str,
    action: str,
    version: str,
    inputs: Mapping[str, str],
    params: Mapping[str, Any] | None = None,
    data_version: str | None = None,
) -> str:
    """생산 단계의 정체.

    입력은 슬롯 이름을 키로 한 매핑으로 해시하므로 나열 순서와 무관하고,
    같은 artifact가 다른 슬롯에 들어가면 다른 키가 된다. params는 루트 단계에만 준다.
    """
    parts = [
        service,
        action,
        version,
        canonical_json(dict(inputs)),
        canonical_json(dict(params) if params else {}),
    ]
    if data_version is not None:  # invalidate()된 적이 없으면 0.2와 같은 키
        parts.append("data_version=" + data_version)
    return _digest("step", *parts)


def params_scope(params: Mapping[str, Any] | None) -> str:
    """invalidate()의 범위 키. params가 없으면 '*' (Action 전체)."""
    if not params:
        return "*"
    return _digest("scope", canonical_json(dict(params)))


def lineage_key(step: str, slot: str) -> str:
    """출력 슬롯 하나의 정체. 출력이 여러 개면 슬롯마다 다른 키가 된다."""
    return _digest("lineage", step, slot)


def _gen(generation: float) -> str:
    return repr(float(generation))


def artifact_id(parents: Iterable[str], lineage: str, generation: float) -> str:
    """저장된 데이터의 정체. 부모 ID가 들어가므로 단계마다 계보가 쌓인다."""
    return _digest("artifact", canonical_json(sorted(parents)), lineage, _gen(generation))


def planned_id(parents: Iterable[str], step: str, slot: str, generation: float) -> str:
    """Planner가 실행 전에 미리 계산하는 artifact_id. Resolver 발급 값과 같아야 한다."""
    return artifact_id(parents, lineage_key(step, slot), generation)


def save_key(lineage: str, generation: float) -> str:
    """Resolver가 (lineage_key, generation)으로 이미 저장된 것을 찾을 때 쓰는 키."""
    return _digest("save", lineage, _gen(generation))


def run_id(seed: str) -> str:
    return _digest("run", seed)[:16]


# --- version -------------------------------------------------------------
def _strip(node: ast.AST) -> ast.AST:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.decorator_list = []
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return node


_SKIP_FIELDS = {"ctx", "type_comment", "kind"}


def _canon(value: Any) -> str:
    """AST를 파이썬 버전과 무관한 문자열로.

    ``ast.dump``는 버전마다 노드에 필드가 늘어(예: 3.12의 ``type_params``) 같은 코드도
    다른 값이 된다.
    여기서는 비어 있는 필드(None, [])와 문맥 표시(ctx)를 빼고 이름을 붙여 적으므로,
    새 버전이 기본값이 빈 필드를 더해도 결과가 같다.
    """
    if isinstance(value, ast.AST):
        parts = []
        for name in value._fields:
            if name in _SKIP_FIELDS:
                continue
            v = getattr(value, name, None)
            if v is None or v == []:
                continue
            parts.append(f"{name}={_canon(v)}")
        return f"{type(value).__name__}({','.join(parts)})"
    if isinstance(value, list):
        return "[" + ",".join(_canon(v) for v in value) + "]"
    return repr(value)


def ast_digest(node: ast.AST) -> str:
    """AST 노드 하나의 짧은 해시. 파이썬 3.11~3.13에서 같은 값을 낸다."""
    return hashlib.sha256(_canon(node).encode()).hexdigest()[:12]


def version_of_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """함수 AST의 정규화 해시. 주석, 공백, 줄 위치, docstring, 데코레이터는 영향을 주지 않는다."""
    copy = ast.parse(ast.unparse(node)).body[0]
    stripped = _strip(copy)
    return ast_digest(stripped)


def version_of_source(source: str) -> str:
    """함수 소스 문자열의 version. 소스는 함수 정의 하나여야 한다."""
    tree = ast.parse(textwrap.dedent(source))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return version_of_node(node)
    raise ValueError("함수 정의를 찾지 못했습니다")

"""DAG 파일 로딩과 검증."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ms_dataflow.config import format_validation, read_yaml
from ms_dataflow.config import types as slot_types
from ms_dataflow.errors import ConfigError
from ms_dataflow.models import Dag, Delivery, split_ref
from ms_dataflow.registry import Registry


def load_dag(path: Path) -> Dag:
    data = read_yaml(path)
    try:
        dag = Dag.model_validate(data)
    except ValidationError as e:
        raise ConfigError(
            format_validation(e), file=str(path), fix="DAG 형식을 확인하세요."
        ) from None
    return dag.model_copy(update={"source": str(path)})


def load_dags(dag_dir: Path) -> tuple[dict[str, Dag], list[ConfigError]]:
    dags: dict[str, Dag] = {}
    errors: list[ConfigError] = []
    if not dag_dir.is_dir():
        return dags, errors
    files = sorted([*dag_dir.glob("*.yaml"), *dag_dir.glob("*.yml")])
    for p in files:
        try:
            dag = load_dag(p)
        except ConfigError as e:
            errors.append(e)
            continue
        except yaml.YAMLError as e:
            errors.append(ConfigError(f"YAML 문법 오류: {e}", file=str(p)))
            continue
        if dag.order in dags:
            errors.append(
                ConfigError(
                    f"order 이름 '{dag.order}'가 두 DAG에 있습니다 "
                    f"(다른 곳: {dags[dag.order].source}).",
                    file=str(p),
                    fix="order 이름은 DAG마다 하나여야 합니다.",
                )
            )
            continue
        dags[dag.order] = dag
    return dags, errors


# --- 그래프 도우미 ------------------------------------------------------------
def incoming(dag: Dag) -> dict[str, dict[str, tuple[str, str]]]:
    """노드 → {입력 슬롯: (부모 노드, 부모 출력 슬롯)}"""
    out: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    for e in dag.edges:
        fn, fs = split_ref(e.from_)
        tn, ts = split_ref(e.to)
        out[tn][ts] = (fn, fs)
    return out


def ancestors(dag: Dag, node: str) -> list[str]:
    """node와 그 조상. 부모가 먼저 오는 순서."""
    inc = incoming(dag)
    order: list[str] = []
    seen: set[str] = set()

    def visit(n: str) -> None:
        if n in seen:
            return
        seen.add(n)
        for parent, _ in inc.get(n, {}).values():
            visit(parent)
        order.append(n)

    visit(node)
    return order


def roots(dag: Dag, nodes: list[str]) -> list[str]:
    inc = incoming(dag)
    return [n for n in nodes if not inc.get(n)]


def delivery_for(dag: Dag, requester: str) -> Delivery | None:
    for d in dag.deliveries:
        if d.requester == requester:
            return d
    return None


def _find_cycle(dag: Dag) -> list[str] | None:
    children: dict[str, list[str]] = defaultdict(list)
    for e in dag.edges:
        children[split_ref(e.from_)[0]].append(split_ref(e.to)[0])
    state: dict[str, int] = {}
    stack: list[str] = []

    def dfs(n: str) -> list[str] | None:
        state[n] = 1
        stack.append(n)
        for c in children.get(n, []):
            if state.get(c) == 1:
                return stack[stack.index(c) :] + [c]
            if c not in state:
                found = dfs(c)
                if found:
                    return found
        stack.pop()
        state[n] = 2
        return None

    for n in dag.nodes:
        if n not in state:
            found = dfs(n)
            if found:
                return found
    return None


def validate_dag(
    dag: Dag, registry: Registry, *, strict_services: bool = True
) -> tuple[list[ConfigError], list[str]]:
    """레지스트리와 대조해 DAG를 검증한다.

    strict_services=False면 레지스트리에 없는 서비스는 경고만 낸다(다른 저장소에 있는 서비스는
    등록 시점에 검사한다).
    """
    errors: list[ConfigError] = []
    warnings: list[str] = []
    src = dag.source

    def err(reason: str, fix: str | None = None) -> None:
        errors.append(ConfigError(reason, file=src, fix=fix))

    specs: dict[str, Any] = {}
    for name, node in dag.nodes.items():
        if node.service not in registry.services:
            msg = f"노드 '{name}'의 서비스 '{node.service}'를 찾지 못했습니다."
            if strict_services:
                err(
                    msg,
                    "서비스 이름을 확인하거나 그 서비스 코드가 프로젝트 안에 있는지 확인하세요.",
                )
            else:
                warnings.append(f"{src}: {msg} 서비스가 등록될 때 다시 검사합니다.")
            continue
        spec = registry.action(node.service, node.action)
        if spec is None:
            known = ", ".join(registry.services[node.service].actions) or "(없음)"
            err(
                f"노드 '{name}': 서비스 '{node.service}'에 Action '{node.action}'이 없습니다.",
                f"있는 Action: {known}",
            )
            continue
        specs[name] = spec

    seen_inputs: set[tuple[str, str]] = set()
    used_outputs: set[tuple[str, str]] = set()
    for e in dag.edges:
        fn, fs = split_ref(e.from_)
        tn, ts = split_ref(e.to)
        for n in (fn, tn):
            if n not in dag.nodes:
                err(f"엣지 {e.from_} → {e.to}: 노드 '{n}'가 없습니다.")
        if fn in specs and fs not in specs[fn].outputs:
            err(
                f"엣지 {e.from_} → {e.to}: '{fn}'에 출력 슬롯 '{fs}'가 없습니다.",
                f"출력 슬롯: {', '.join(specs[fn].outputs)}",
            )
        if tn in specs and ts not in specs[tn].inputs:
            err(
                f"엣지 {e.from_} → {e.to}: '{tn}'에 입력 슬롯 '{ts}'가 없습니다.",
                f"입력 슬롯: {', '.join(specs[tn].inputs) or '(없음)'}",
            )
        if (
            fn in specs
            and tn in specs
            and fs in specs[fn].outputs
            and ts in specs[tn].inputs
            and not slot_types.compatible(
                slot_types.output_type(specs[fn], fs), slot_types.input_type(specs[tn], ts)
            )
        ):
            a, b = specs[fn], specs[tn]
            err(
                f"엣지 {e.from_} → {e.to}: 타입이 맞지 않습니다. "
                f"{a.service}.{a.name}이 '{slot_types.output_type(a, fs)}'를 내보내는데 "
                f"{b.service}.{b.name}의 '{ts}'는 '{slot_types.input_type(b, ts)}'를 받습니다.\n"
                f"  ({a.file}:{a.lineno}, {b.file}:{b.lineno})",
                "연결을 고치거나, 두 함수의 타입 힌트를 맞추세요. "
                "의도한 것이라면 받는 쪽 힌트를 넓히세요(예: Any, 공통 부모 클래스).",
            )
        if (tn, ts) in seen_inputs:
            err(f"입력 슬롯 {e.to}에 엣지가 두 개 연결되어 있습니다.")
        seen_inputs.add((tn, ts))
        used_outputs.add((fn, fs))

    cycle = _find_cycle(dag)
    if cycle:
        err("DAG에 순환이 있습니다: " + " → ".join(cycle))

    inc = incoming(dag)
    for name, spec in specs.items():
        for slot in spec.inputs:
            if slot not in inc.get(name, {}):
                err(
                    f"노드 '{name}'의 입력 슬롯 '{slot}'이 연결되어 있지 않습니다.",
                    f"edges에 {{from: <노드>.<출력>, to: {name}.{slot}}}를 추가하세요.",
                )
        if spec.params and inc.get(name):
            err(
                f"노드 '{name}'의 Action이 params를 선언했지만 첫 단계가 아닙니다.",
                "params는 입력 엣지가 없는 첫 단계 Action만 받을 수 있습니다.",
            )

    rn, rs = split_ref(dag.result)
    if rn not in dag.nodes:
        err(f"result '{dag.result}': 노드 '{rn}'가 없습니다.")
    elif rn in specs and rs not in specs[rn].outputs:
        err(f"result '{dag.result}': 출력 슬롯 '{rs}'가 없습니다.")
    used_outputs.add((rn, rs))

    requesters: set[str] = set()
    for d in dag.deliveries:
        if d.requester in requesters:
            err(f"requester '{d.requester}'의 delivery가 두 번 있습니다.")
        requesters.add(d.requester)
        for kind, ref in (("on_success", d.on_success), ("on_fail", d.on_fail)):
            svc, act = split_ref(ref)
            if svc != d.requester:
                err(
                    f"{kind} '{ref}'는 요청한 서비스 '{d.requester}'의 Action이어야 합니다.",
                    f"{d.requester}.<action> 형태로 적으세요.",
                )
                continue
            if svc not in registry.services:
                if strict_services:
                    err(f"{kind} '{ref}': 서비스 '{svc}'를 찾지 못했습니다.")
                continue
            spec = registry.action(svc, act)
            if spec is None:
                err(f"{kind} '{ref}': 서비스 '{svc}'에 Action '{act}'이 없습니다.")
                continue
            if (
                kind == "on_success"
                and len(spec.inputs) == 1
                and rn in specs
                and rs in specs[rn].outputs
                and not slot_types.compatible(
                    slot_types.output_type(specs[rn], rs),
                    slot_types.input_type(spec, spec.inputs[0]),
                )
            ):
                r = specs[rn]
                err(
                    f"on_success '{ref}': 타입이 맞지 않습니다. 결과 {dag.result}는 "
                    f"'{slot_types.output_type(r, rs)}'인데 '{spec.inputs[0]}'는 "
                    f"'{slot_types.input_type(spec, spec.inputs[0])}'를 받습니다.\n"
                    f"  ({r.file}:{r.lineno}, {spec.file}:{spec.lineno})",
                    "결과를 받는 Action의 타입 힌트를 결과 타입에 맞추세요.",
                )
            if kind == "on_success" and len(spec.inputs) != 1:
                err(
                    f"on_success '{ref}'는 입력 슬롯이 정확히 하나여야 합니다 "
                    f"(지금: {len(spec.inputs)}개).",
                    '@action(inputs=["result"])처럼 결과를 받을 슬롯 하나를 선언하세요.',
                )
            if kind == "on_fail" and not spec.args:
                err(
                    f"on_fail '{ref}'는 실패 사유(status)를 받을 인자가 하나 있어야 합니다.",
                    "def on_fail(status: str): ...",
                )

    for name, spec in specs.items():
        for slot in spec.outputs:
            if (name, slot) not in used_outputs:
                warnings.append(f"{src}: 출력 슬롯 {name}.{slot}이 어디에도 연결되지 않았습니다.")
    return errors, warnings

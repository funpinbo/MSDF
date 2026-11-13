"""구조 guard: 각 부분이 책임 하나만 지는지.

데이터는 Resolver, 출처는 Artifact 테이블(엔진), 권한은 IAM, 순서는 Planner.
"""

from __future__ import annotations

import re

from _util import PKG, ROOT, imports_of, rule

# 엔진 없이도 동작해야 하는 핵심 (데코레이터, msdf check). 서버 쪽 라이브러리를 import하면 안 된다
CORE = [
    "ids.py",
    "models.py",
    "decorators.py",
    "errors.py",
    "planner.py",
    "project.py",
    "registry/__init__.py",
    "registry/scan.py",
    "config/__init__.py",
    "config/dag.py",
    "config/iam.py",
    "config/resolvers.py",
]
SERVER_ONLY = (
    "fastapi",
    "uvicorn",
    "httpx",
    "sqlite3",
    "ms_dataflow.execute",
    "ms_dataflow.store",
    "ms_dataflow.ui",
    "ms_dataflow.client",
)


def test_core_does_not_depend_on_the_server():
    bad = {}
    for rel in CORE:
        used = {m for m in imports_of(PKG / rel) if m.startswith(SERVER_ONLY)}
        if used:
            bad[rel] = sorted(used)
    assert not bad, rule(
        "핵심 모듈은 서버 없이 동작한다 (extras 없이 설치해도 msdf check와 데코레이터가 된다).",
        "서비스는 runtime 묶음만, 코드 검사는 아무 묶음 없이 설치할 수 있어야 한다.",
        "서버가 필요한 코드는 ms_dataflow/execute, ui, client 쪽에 둔다. 꼭 필요하면 함수 안에서 늦게 import한다.",
        bad,
    )


def test_planner_is_a_pure_function():
    used = imports_of(PKG / "planner.py")
    forbidden = sorted(
        m
        for m in used
        if m.startswith(
            ("ms_dataflow.store", "ms_dataflow.execute", "sqlite3", "time", "random", "uuid", "os")
        )
    )
    assert not forbidden, rule(
        "Planner는 순수 함수다: DB, 시계, 난수, 환경에 기대지 않는다.",
        "같은 입력이면 같은 계획이어야 cache와 테스트를 믿을 수 있다.",
        "필요한 값은 lookup(PlanLookup)이나 인자(now)로 주입한다.",
        forbidden,
    )


# 메타데이터 DB에 쓰는 곳. resolvers/sqlite.py는 사용자 데이터 저장소라 별개다
SQL_WRITERS = {"execute/engine.py", "ops.py", "resolvers/sqlite.py"}
_WRITE = re.compile(r"\b(INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.I)


def test_only_the_engine_writes_metadata():
    writers = {
        str(f.relative_to(PKG)) for f in PKG.rglob("*.py") if _WRITE.search(f.read_text("utf-8"))
    }
    assert writers <= SQL_WRITERS, rule(
        "메타데이터 DB에 쓰는 것은 엔진(engine.py, ops.py)뿐이다.",
        "SQLite 작성자를 하나로 두어야 동시 쓰기 문제가 없고, 상태 변화를 한 곳에서 추적할 수 있다.",
        "Engine에 메서드를 추가하고, 다른 곳에서는 그 메서드를 부른다(Scheduler는 sched.db(...)로).",
        sorted(writers - SQL_WRITERS),
    )


HASHERS = {"ids.py", "registry/__init__.py", "resolvers/base.py"}


def test_ids_are_computed_in_one_place():
    users = {
        str(f.relative_to(PKG))
        for f in PKG.rglob("*.py")
        if re.search(r"^\s*(import hashlib|from hashlib)", f.read_text("utf-8"), re.M)
    }
    assert users <= HASHERS, rule(
        "데이터 ID와 버전 해시는 ids.py 한 곳에서 계산한다.",
        "Planner가 미리 계산한 ID와 Resolver가 발급한 ID가 다르면 cache가 전부 어긋난다.",
        "ms_dataflow.ids에 함수를 추가해서 쓴다 (registry의 helper 버전, resolver의 checksum만 예외).",
        sorted(users - HASHERS),
    )


def test_no_print_in_library_code():
    allowed = {"cli.py", "scaffold.py"}
    found = []
    for f in PKG.rglob("*.py"):
        rel = str(f.relative_to(PKG))
        if rel in allowed:
            continue
        for i, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            if re.match(r"\s*print\(", line):
                found.append(f"{rel}:{i}")
    assert not found, rule(
        "라이브러리 코드는 print하지 않는다.",
        "사용자 서비스의 표준 출력을 더럽힌다. 엔진 로그는 UI의 엔진 로그 탭에서 본다.",
        "logging.getLogger('msdf.…')를 쓴다.",
        found,
    )


def test_wire_models_are_backward_compatible():
    """엔진 ↔ 서비스 메시지에 새 필드는 기본값을 가져야 한다 (옛 서비스가 그대로 붙도록)."""
    from ms_dataflow import models

    required_ok = {
        "RegisterRequest": {"instance_id", "address", "services", "actions"},
        "OrderRequest": {"instance_id", "requester", "name"},
        "StepTask": {"run_id", "step_no", "kind", "service", "action"},
        "StepResult": {"run_id", "step_no", "ok"},
        "ResultReport": {"instance_id", "result"},
        "InvalidateRequest": {"instance_id", "requester", "action"},
        "CancelRequest": {"instance_id", "requester", "request_id"},
        "DeleteRequest": {"instance_id", "requester", "lineage_key"},
    }
    bad = {}
    for name, allowed in required_ok.items():
        cls = getattr(models, name)
        required = {n for n, f in cls.model_fields.items() if f.is_required()}
        if required - allowed:
            bad[name] = sorted(required - allowed)
    assert not bad, rule(
        "엔진과 서비스 사이 메시지에 추가하는 필드는 기본값을 가진다.",
        "필수 필드를 더하면 이전 버전으로 띄운 서비스가 엔진에 붙지 못한다.",
        "새 필드에 기본값(None, 빈 dict 등)을 준다. 정말 필수로 바꿔야 하면 CHANGELOG의 '바뀐 것'에 적고 이 목록을 고친다.",
        bad,
    )


def test_tests_use_the_neutral_fixture_not_examples():
    """프레임워크 동작은 도메인 없는 tests/fixtures/calc로 검증한다."""
    found = []
    for f in (ROOT / "tests").glob("test_*.py"):  # guards/와 e2e/는 제외
        if f.name == "test_examples.py":
            continue
        if re.search(r"""["']examples["']""", f.read_text("utf-8")):
            found.append(f.name)
    assert not found, rule(
        "프레임워크 테스트는 tests/fixtures/calc로 한다. examples/는 사용자에게 보여 주는 예시다.",
        "예시가 바뀔 때마다 프레임워크 테스트가 깨지면 안 된다.",
        "필요한 서비스는 tests/fixtures에 최소한으로 만든다.",
        found,
    )

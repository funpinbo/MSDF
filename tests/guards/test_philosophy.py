"""철학 guard: MSDF가 지키기로 한 선을 기여가 넘지 않는지.

> 서비스 사이 데이터 이동의 권한, 실패, 추적을 쉽게 하는 계층이지, 서비스 전체를 관리하는 시스템이 아니다.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from _util import PKG, ROOT, imports_of, rule

import ms_dataflow
from ms_dataflow.registry import collect

PUBLIC_API = {
    "service",
    "action",
    "order",
    "start",
    "context",
    "delete",
    "invalidate",
    "cancel",  # 0.4: 요청 취소와 구독 끝내기를 하나로 (unsubscribe를 따로 두지 않는다)
}


def test_public_api_is_small_and_deliberate():
    assert set(ms_dataflow.__all__) == PUBLIC_API, rule(
        "사용자가 외울 것을 줄인다: 공개 함수는 이 목록이 전부다.",
        "공개 함수가 하나 늘 때마다 모든 사용자가 배울 것이 는다.",
        "정말 필요하면 이슈에서 먼저 합의하고, 이 테스트의 PUBLIC_API와 "
        "docs/writing-services.md(ko/en)를 함께 고친다.",
        sorted(set(ms_dataflow.__all__) ^ PUBLIC_API),
    )


def _allowed(module: str) -> bool:
    return (
        module == "ms_dataflow"
        or module in {f"ms_dataflow.{n}" for n in PUBLIC_API}
        or module == "ms_dataflow.errors"
        or module.startswith("ms_dataflow.errors.")
    )


def _service_files(root):
    reg = collect(root)
    return reg, {f for s in reg.services.values() for f in s.files}


def test_service_code_never_touches_engine_internals():
    """예시 서비스 코드에는 ID, 큐, HTTP, 저장소가 나오지 않는다."""
    _, files = _service_files(ROOT / "examples" / "chatbot")
    bad = {}
    for f in sorted(files):
        extra = sorted(
            m for m in imports_of(Path(f)) if m.startswith("ms_dataflow") and not _allowed(m)
        )
        if extra:
            bad[f] = extra
    assert files and not bad, rule(
        "서비스 코드에는 데이터 ID, 큐, HTTP, 직렬화, 저장소가 나오지 않는다.",
        "그것들이 사용자 코드에 나오면 추상화가 깨진 것이다.",
        "서비스는 `from ms_dataflow import ...`(공개 함수)와 `ms_dataflow.errors`만 쓰게 한다.",
        bad,
    )


def test_services_do_not_know_each_other():
    root = ROOT / "examples" / "chatbot"
    reg, _ = _service_files(root)
    entries = {s.name: s.file for s in reg.services.values()}
    crossed = []
    for s in reg.services.values():
        for other, entry in entries.items():
            if other != s.name and entry in s.files:
                crossed.append(f"{s.name} → {other}")
    assert not crossed, rule(
        "서비스는 서로를 모른다.",
        "다른 서비스 파일을 import하면 그 서비스가 바뀔 때 함께 깨진다. 연결은 DAG에서만 한다.",
        "필요한 결과는 order()로 요청하고, 연결은 dags/*.yaml에 적는다.",
        crossed,
    )


BANNED_DEPS = {
    # 스케줄러가 아니다 (cron, 주기 실행은 하지 않는다)
    "apscheduler",
    "croniter",
    "celery",
    "schedule",
    "rq",
    "dramatiq",
    # 서비스를 띄우거나 배포하지 않는다
    "kubernetes",
    "docker",
    # LLM 전용 기능을 넣지 않는다 (범용 데이터 흐름 계층)
    "openai",
    "anthropic",
    "langchain",
    "langgraph",
    "llama-index",
    "transformers",
}
CORE_DEPS = {"pydantic", "pyyaml"}


def _dep_names(specs):
    return {re.split(r"[<>=!~\[ ;@]", s.strip(), maxsplit=1)[0].lower() for s in specs}


def test_dependencies_stay_inside_the_scope():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    core = _dep_names(meta["dependencies"])
    extras = set().union(*(_dep_names(v) for v in meta["optional-dependencies"].values()))
    assert core <= CORE_DEPS, rule(
        "핵심 설치는 가볍게: 데코레이터와 msdf check는 pydantic, pyyaml만으로 동작한다.",
        "서비스마다 설치하므로 의존성 하나가 모든 사용자에게 퍼진다.",
        "새 기능의 의존성은 extras(runtime, server, dataframe)에 둔다.",
        sorted(core - CORE_DEPS),
    )
    banned = (core | extras) & BANNED_DEPS
    assert not banned, rule(
        "MSDF는 스케줄러, 배포 도구, LLM 프레임워크가 아니다.",
        "범위를 넘으면 '서비스 사이 데이터 이동 계층'이라는 정체성이 흐려진다.",
        "그 기능은 서비스 쪽 코드에 두거나, 이슈에서 범위를 먼저 논의한다.",
        sorted(banned),
    )


def test_no_scheduling_or_service_management_in_the_package():
    patterns = re.compile(r"\b(crontab|croniter|apscheduler|subprocess\.Popen|docker\.from_env)\b")
    found = []
    for f in PKG.rglob("*.py"):
        for i, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            if patterns.search(line):
                found.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not found, rule(
        "엔진은 주기 실행을 하지 않고, 서비스를 띄우거나 관리하지 않는다.",
        "언제 데이터가 바뀌었는지는 데이터를 아는 서비스가 판단한다(invalidate). 서비스 실행은 사용자 몫이다.",
        "주기적 갱신이 필요하면 서비스가 invalidate()/order()를 부르게 한다.",
        found,
    )


def test_meta_never_reaches_the_cache_key():
    """meta는 '누구에게 돌려줄지'일 뿐 '무엇을 계산할지'가 아니다."""
    planner = (PKG / "planner.py").read_text("utf-8")
    ids_src = (PKG / "ids.py").read_text("utf-8")
    assert "meta" not in planner and "meta" not in ids_src, rule(
        "meta는 cache key에 들어가지 않는다.",
        "meta가 key에 들어가면 사용자마다 같은 계산을 반복한다.",
        "계산에 영향을 주는 값은 params로 받는다.",
    )

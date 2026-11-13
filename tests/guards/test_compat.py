"""호환성 guard: 사용자의 cache와 DB를 조용히 깨뜨리지 않는지.

이 값들이 바뀌면 모든 사용자의 cache가 한 번에 무효가 되거나, 서로 다른 버전의 엔진과 서비스가 어긋난다.
의도한 변경이라면 값을 고치고 CHANGELOG의 '바뀐 것'에 적는다.
"""

from __future__ import annotations

import hashlib
import json
import tomllib

from _util import ROOT, rule

import ms_dataflow
from ms_dataflow import ids
from ms_dataflow.store import MIGRATIONS, SCHEMA_VERSION, _schema_sql

GOLDEN = {
    "step": "7cc04ff05b4b26fe07b6e0d4406e8466",
    "step_dv": "9d265287487ea8bf8e868b9db944caa8",
    "lineage": "5cb1fa61c664f66717855856afa17d9c",
    "artifact": "d5a6fba14e9850ba819aa2b448501a53",
    "scope": "c6474671e7c638248e80303b6394ab9a",
}
CACHE_RULE = (
    "cache key(step_key, lineage_key, artifact_id)는 버전이 올라가도 같은 입력이면 같다.",
    "바뀌면 모든 사용자의 cache가 한 번에 무효가 되고, 다른 버전의 엔진과 서비스가 어긋난다.",
    "의도한 변경이면 GOLDEN 값을 고치고 CHANGELOG(ko/en)의 '바뀐 것'에 cache가 다시 계산된다고 적는다.",
)


def test_cache_keys_are_stable():
    sk = ids.step_key("svc", "act", "v1", {"x": "a" * 32}, {"day": "2026-11-12"})
    got = {
        "step": sk,
        "step_dv": ids.step_key("svc", "act", "v1", {"x": "a" * 32}, {"day": "2026-11-12"}, "*=v9"),
        "lineage": ids.lineage_key(sk, "out"),
        "artifact": ids.artifact_id(["p1", "p2"], ids.lineage_key(sk, "out"), 1700000000.5),
        "scope": ids.params_scope({"q": "refund"}),
    }
    assert got == GOLDEN, rule(*CACHE_RULE, {k: v for k, v in got.items() if GOLDEN[k] != v})
    assert ids.planned_id(["p1", "p2"], sk, "out", 1700000000.5) == got["artifact"], rule(
        "Planner가 미리 계산한 ID와 Resolver가 발급하는 ID는 같다.",
        "다르면 엔진이 그 단계를 실패로 처리한다.",
        "ids.planned_id와 ids.artifact_id가 같은 재료를 쓰게 한다.",
    )


# 이 테스트는 CI에서 파이썬 3.11, 3.12, 3.13 모두에서 돈다. 셋 다 같은 값이어야 한다
VERSION_GOLDEN = {
    "def f(x):\n    return x + 1\n": "1b69e9c152f4",
    "async def g(a, *, b=2) -> int:\n    return [i for i in range(a)]\n": "5b9c11cc5a57",
    'def h():\n    with open("x") as f:\n        return f.read()\n': "b48824f1eff7",
}


def test_action_version_is_the_same_on_every_python():
    got = {src: ids.version_of_source(src) for src in VERSION_GOLDEN}
    assert got == VERSION_GOLDEN, rule(
        "Action 버전은 파이썬 버전과 무관하게 같은 코드면 같다.",
        "다르면 엔진과 서비스를 다른 파이썬으로 띄울 때 같은 코드가 '다른 코드'로 거부되고, "
        "파이썬만 올려도 cache가 전부 무효가 된다.",
        "ids.ast_digest(정규화)를 쓰고 ast.dump를 쓰지 않는다. 의도한 변경이면 값을 고치고 CHANGELOG에 적는다.",
        {s.splitlines()[0]: v for s, v in got.items() if VERSION_GOLDEN[s] != v},
    )


def test_version_ignores_formatting():
    a = "def f(x):\n    '''doc'''\n    # comment\n    return x+1\n"
    b = "def f(x):\n    return (x + 1)\n"
    assert ids.version_of_source(a) == ids.version_of_source(b)


SCHEMA_GOLDEN = {4: "ade493a2b6e98d26"}


def test_schema_changes_come_with_a_migration():
    digest = hashlib.sha256(_schema_sql().encode()).hexdigest()[:16]
    assert SCHEMA_GOLDEN.get(SCHEMA_VERSION) == digest, rule(
        "DB 구조(schema.sql)를 바꾸면 SCHEMA_VERSION을 올리고 MIGRATIONS에 변환을 추가한다.",
        "그러지 않으면 기존 사용자의 .msdf/msdf.db가 새 코드와 어긋난다.",
        "store/__init__.py의 SCHEMA_VERSION += 1, MIGRATIONS[이전 버전] = 'ALTER ...', "
        "tests/test_store.py에 변환 테스트, 그리고 이 SCHEMA_GOLDEN에 새 해시를 추가한다.",
        {"SCHEMA_VERSION": SCHEMA_VERSION, "schema.sql 해시": digest},
    )
    assert set(MIGRATIONS) == set(range(1, SCHEMA_VERSION)), rule(
        "모든 이전 스키마 버전에서 현재 버전으로 가는 변환이 있다.",
        "빠지면 그 버전의 DB를 가진 사용자는 시작할 수 없다.",
        "MIGRATIONS에 빠진 버전을 추가한다 (표만 추가했다면 빈 문자열).",
        sorted(set(range(1, SCHEMA_VERSION)) ^ set(MIGRATIONS)),
    )


def test_versions_agree_everywhere():
    py = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    ui = json.loads((ROOT / "frontend" / "package.json").read_text("utf-8"))["version"]
    assert py == ms_dataflow.__version__ == ui, rule(
        "버전은 pyproject.toml, ms_dataflow.__version__, frontend/package.json이 같다.",
        "한 곳만 올리면 msdf --version과 설치된 패키지가 다른 버전을 말한다.",
        "세 곳을 함께 고친다.",
        {"pyproject": py, "__version__": ms_dataflow.__version__, "frontend": ui},
    )
    for name in ("CHANGELOG.md", "CHANGELOG.en.md"):
        text = (ROOT / name).read_text("utf-8")
        assert f"## {py}" in text, rule(
            "버전마다 변경 기록이 한국어와 영어 두 벌 있다.",
            "사용자는 CHANGELOG로 무엇이 바뀌었는지, cache나 DB에 영향이 있는지 안다.",
            f"{name}에 '## {py}' 항목을 추가한다.",
        )

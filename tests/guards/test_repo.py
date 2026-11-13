"""저장소 guard: 들어가면 안 되는 것이 커밋되지 않았는지."""

from __future__ import annotations

import re

import pytest
from _util import ROOT, rule, tracked_files

FILES = tracked_files()
pytestmark = pytest.mark.skipif(not FILES, reason="git 저장소가 아니다")


def test_no_build_output_or_local_state_is_committed():
    bad = [
        f
        for f in FILES
        if f.startswith(("design/", "ms_dataflow/ui/dist/", "frontend/node_modules/", "dist/"))
        or "/.msdf/" in f
        or f.startswith(".msdf/")
        or f.endswith((".db", ".pyc", ".whl"))
    ]
    assert not bad, rule(
        "빌드 결과, 로컬 상태, 설계 메모는 커밋하지 않는다.",
        "UI는 소스만 배포하고(라이선스), .msdf는 사용자 로컬 cache다. design/은 내부 메모다.",
        "git rm --cached로 빼고 .gitignore를 확인한다.",
        bad[:20],
    )


def test_every_python_file_parses_and_has_no_leftovers():
    found = []
    for f in FILES:
        if not f.endswith(".py"):
            continue
        text = (ROOT / f).read_text("utf-8")
        compile(text, f, "exec")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\b(breakpoint\(\)|pdb\.set_trace|import pdb)\b", line):
                found.append(f"{f}:{i}: {line.strip()}")
    assert not found, rule(
        "디버깅 흔적을 남기지 않는다.",
        "breakpoint()가 서비스 프로세스에서 불리면 단계가 멈춘다.",
        "지우고 다시 커밋한다.",
        found,
    )


SECRET = re.compile(
    r"(AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{32,})"
)


def test_no_secrets_committed():
    found = []
    for f in FILES:
        p = ROOT / f
        if p.suffix in {".png", ".ico", ".lock"} or f.endswith("package-lock.json"):
            continue
        try:
            text = p.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SECRET.search(text):
            found.append(f)
    assert not found, rule(
        "비밀 값(API 키, 개인 키, 토큰)은 커밋하지 않는다.",
        "공개 저장소다. 한 번 올라간 키는 지워도 기록에 남는다.",
        "키를 폐기하고, 환경 변수(MSDF_TOKEN 등)로 받게 고친다.",
        found,
    )

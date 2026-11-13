"""문서 guard: 문서가 코드와 맞고, 한국어와 영어가 같은 내용인지."""

from __future__ import annotations

import ast
import re

import pytest
from _util import ROOT, rule

import ms_dataflow

PAIRS = [
    (ROOT / "README.md", ROOT / "README.en.md"),
    (ROOT / "CONTRIBUTING.md", ROOT / "CONTRIBUTING.en.md"),
    (ROOT / "CHANGELOG.md", ROOT / "CHANGELOG.en.md"),
    (ROOT / "frontend" / "README.md", ROOT / "frontend" / "README.en.md"),
    (ROOT / "examples" / "chatbot" / "README.md", ROOT / "examples" / "chatbot" / "README.en.md"),
] + [(p, ROOT / "docs" / "en" / p.name) for p in sorted((ROOT / "docs").glob("*.md"))]

ALL_DOCS = [p for pair in PAIRS for p in pair if p.exists()]


def test_every_document_has_both_languages():
    missing = [str(b.relative_to(ROOT)) for a, b in PAIRS if a.exists() and not b.exists()]
    extra = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "docs" / "en").glob("*.md")
        if not (ROOT / "docs" / p.name).exists()
    ]
    assert not missing and not extra, rule(
        "문서는 한국어와 영어 두 벌이다.",
        "한쪽만 있으면 그 언어 사용자는 다른 내용을 보게 된다.",
        "짝이 되는 파일(docs/X.md ↔ docs/en/X.md, *.md ↔ *.en.md)을 함께 만든다.",
        missing + extra,
    )


def _shape(text: str) -> tuple[int, int, int]:
    headings = len(re.findall(r"^#{1,4} ", text, re.M))
    fences = text.count("```")
    tables = len(re.findall(r"^\|\s*-{3}", text, re.M))
    return headings, fences, tables


@pytest.mark.parametrize(
    "ko,en", [p for p in PAIRS if all(x.exists() for x in p)], ids=lambda p: p.name
)
def test_korean_and_english_have_the_same_shape(ko, en):
    a, b = _shape(ko.read_text("utf-8")), _shape(en.read_text("utf-8"))
    assert a == b, rule(
        "한국어와 영어 문서는 같은 내용이다 (제목, 코드 블록, 표 수가 같다).",
        "한쪽만 고치면 두 언어의 설명이 달라진다.",
        f"{ko.relative_to(ROOT)}와 {en.relative_to(ROOT)}를 같이 고친다.",
        {"(제목, 코드 블록 경계, 표)": {"ko": a, "en": b}},
    )


def test_every_public_function_is_documented():
    for doc in ("docs/writing-services.md", "docs/en/writing-services.md"):
        text = (ROOT / doc).read_text("utf-8")
        missing = [n for n in ms_dataflow.__all__ if not re.search(rf"`@?{n}\b", text)]
        assert not missing, rule(
            "공개 함수는 모두 '서비스 작성하기' 문서에 있다.",
            "문서에 없는 기능은 없는 것과 같다.",
            f"{doc}에 사용법을 추가한다.",
            missing,
        )


def test_every_cli_command_is_documented():
    from ms_dataflow import cli

    src = (ROOT / "ms_dataflow" / "cli.py").read_text("utf-8")
    commands = re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', src)
    assert commands, "cli.py에서 명령을 찾지 못했다"
    assert cli  # import 가능
    for doc in ("docs/configuration.md", "docs/en/configuration.md"):
        text = (ROOT / doc).read_text("utf-8")
        missing = [c for c in commands if f"msdf {c}" not in text]
        assert not missing, rule(
            "msdf 명령은 모두 '설정' 문서의 명령 목록에 있다.",
            "사용자는 문서를 보고 명령을 찾는다.",
            f"{doc}의 'msdf 명령' 절에 추가한다.",
            missing,
        )


LINK = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")


def test_relative_links_point_to_existing_files():
    broken = []
    for doc in ALL_DOCS:
        for m in LINK.finditer(doc.read_text("utf-8")):
            target = m.group(1)
            if re.match(r"[a-z]+:", target):  # http:, https:, mailto:
                continue
            if not (doc.parent / target).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} → {target}")
    assert not broken, rule(
        "문서의 상대 링크는 실제 파일을 가리킨다.",
        "깨진 링크는 처음 온 사용자를 막다른 길로 보낸다.",
        "경로를 고치거나, 옮긴 파일의 링크를 함께 고친다 (docs/en/에서는 ../ 경로에 주의).",
        broken,
    )


def test_python_examples_in_docs_parse():
    bad = []
    for doc in ALL_DOCS:
        text = doc.read_text("utf-8")
        for m in re.finditer(r"```python\n(.*?)```", text, re.S):
            try:
                ast.parse(m.group(1))
            except SyntaxError as e:
                line = text[: m.start()].count("\n") + 1 + (e.lineno or 0)
                bad.append(f"{doc.relative_to(ROOT)}:{line}: {e.msg}")
    assert not bad, rule(
        "문서의 파이썬 예시는 문법이 맞는 코드다.",
        "사용자는 예시를 복사해서 쓴다.",
        "예시를 고친다. 생략은 `...` 대신 실제 코드나 주석으로 쓴다.",
        bad,
    )

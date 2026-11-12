from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def calc(tmp_path, monkeypatch):
    """calc 픽스처 프로젝트를 임시 폴더에 복사하고 로그 파일을 지정한다."""
    root = tmp_path / "calc"
    shutil.copytree(FIXTURES / "calc", root)
    log = tmp_path / "calc.log"
    log.write_text("")
    monkeypatch.setenv("CALC_LOG", str(log))
    monkeypatch.delenv("CALC_FAIL", raising=False)
    return root


def read_log(root: Path) -> list[tuple[str, object]]:
    log = root.parent / "calc.log"
    return [
        (e["event"], e["value"])
        for e in (json.loads(line) for line in log.read_text().splitlines() if line)
    ]


def clear_log(root: Path) -> None:
    (root.parent / "calc.log").write_text("")

"""묶음 없이 설치한 경우 (fastapi, uvicorn, httpx가 없을 때)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

BLOCK = """
import builtins, sys
_real = builtins.__import__
def _imp(name, *a, **k):
    if name.split('.')[0] in ('fastapi', 'uvicorn', 'httpx', 'starlette'):
        raise ImportError(f"No module named '{name}'", name=name)
    return _real(name, *a, **k)
builtins.__import__ = _imp
"""


def run(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", BLOCK + code], cwd=cwd, capture_output=True, text=True, timeout=60
    )


def test_core_works_without_extras(calc):
    r = run(
        "import ms_dataflow\n"
        "from ms_dataflow import service, action, order, context, delete\n"
        f"from ms_dataflow.cli import main\nsys.exit(main(['check', '--root', r'{calc}']))\n",
        ROOT,
    )
    assert r.returncode == 0, r.stderr
    assert "서비스 3개" in r.stdout


def test_start_and_up_explain_missing_extras(calc):
    r = run("from ms_dataflow import start\nstart()\n", calc)
    assert "runtime 묶음" in r.stderr
    r = run(
        f"from ms_dataflow.cli import main\nsys.exit(main(['up', '--root', r'{calc}']))\n", ROOT
    )
    assert r.returncode == 1 and "server 묶음" in r.stderr

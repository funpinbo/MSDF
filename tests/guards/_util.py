"""guard 테스트 공용. 실패 메시지는 기여자가 이유와 고칠 방법을 바로 알 수 있게 쓴다."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "ms_dataflow"


def rule(what: str, why: str, fix: str, found: object = None) -> str:
    msg = f"\n[원칙] {what}\n[이유] {why}\n[고칠 방법] {fix}"
    if found:
        msg += f"\n[발견] {found}"
    return msg


def imports_of(path: Path) -> set[str]:
    """파일이 import하는 모듈 이름(절대 이름 기준). TYPE_CHECKING 블록은 뺀다."""
    tree = ast.parse(path.read_text("utf-8"))
    out: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for n in nodes:
            if isinstance(n, ast.If) and "TYPE_CHECKING" in ast.unparse(n.test):
                visit(n.orelse)
                continue
            if isinstance(n, ast.Import):
                out.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                out.add(n.module)
                out.update(f"{n.module}.{a.name}" for a in n.names)
            for child in ast.iter_child_nodes(n):
                if isinstance(child, ast.stmt):
                    visit([child])

    visit(tree.body)
    return out


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return out.splitlines()

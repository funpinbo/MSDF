"""로딩 검증 표(docs/configuration.md)의 항목마다 테스트 하나 이상."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from ms_dataflow.errors import ConfigError, LoadError
from ms_dataflow.project import load_project

FIXTURES = Path(__file__).parent / "fixtures"

BASE = """
order: number
nodes:
  make:   {service: src, action: make}
  add:    {service: mid, action: add}
  double: {service: mid, action: double}
edges:
  - {from: make.out, to: add.x}
  - {from: add.out, to: double.x}
result: double.out
deliveries:
  - {requester: req, on_success: req.on_done, on_fail: req.on_fail}
"""


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURES / "calc", root)
    return root


def set_dag(root: Path, text: str, name: str = "number.yaml") -> None:
    (root / "dags" / name).write_text(textwrap.dedent(text))


def errors_of(root: Path) -> str:
    with pytest.raises(LoadError) as e:
        load_project(root)
    return str(e.value)


def test_fixture_loads(project):
    p = load_project(project)
    assert set(p.dags) == {"number"}


def test_cycle(project):
    set_dag(
        project,
        BASE.replace(
            "- {from: add.out, to: double.x}",
            "- {from: double.out, to: add.x}\n  - {from: add.out, to: double.x}",
        ),
    )
    assert "순환" in errors_of(project)


def test_unconnected_input(project):
    set_dag(project, BASE.replace("  - {from: add.out, to: double.x}\n", ""))
    assert "연결되어 있지 않습니다" in errors_of(project)


def test_unknown_action_and_slot(project):
    set_dag(project, BASE.replace("action: double}", "action: triple}"))
    assert "Action 'triple'이 없습니다" in errors_of(project)
    set_dag(project, BASE.replace("to: double.x", "to: double.y"))
    assert "입력 슬롯 'y'가 없습니다" in errors_of(project)


def test_duplicate_order(project):
    set_dag(project, BASE, "copy.yaml")
    assert "두 DAG" in errors_of(project)


def test_bad_result_and_delivery_refs(project):
    set_dag(project, BASE.replace("result: double.out", "result: double.nope"))
    assert "출력 슬롯 'nope'" in errors_of(project)
    set_dag(project, BASE.replace("on_success: req.on_done", "on_success: req.missing"))
    assert "Action 'missing'" in errors_of(project)


def test_on_fail_required(project):
    set_dag(project, BASE.replace(", on_fail: req.on_fail", ""))
    msg = errors_of(project)
    assert "on_fail" in msg and "필수" in msg


def test_dag_cannot_override_version(project):
    set_dag(project, BASE.replace("action: add}", "action: add, version: '2'}"))
    assert "version을 덮어쓸 수 없습니다" in errors_of(project)


def test_unconnected_output_is_warning(project):
    set_dag(
        project,
        BASE.replace("result: double.out", "result: add.out").replace(
            "  - {from: add.out, to: double.x}\n", "  - {from: add.out, to: double.x}\n"
        ),
    )
    p = load_project(project)
    assert any("double.out" in w for w in p.warnings)


def test_params_only_on_root(project):
    (project / "mid.py").write_text(
        (project / "mid.py")
        .read_text()
        .replace(
            '@action(inputs=["x"])\ndef double(x):',
            '@action(inputs=["x"], params=["n"])\ndef double(x, n):',
        )
    )
    assert "첫 단계가 아닙니다" in errors_of(project)


def test_errors_are_collected_together(project):
    set_dag(
        project,
        BASE.replace("action: double}", "action: triple}").replace(
            "result: double.out", "result: zzz.out"
        ),
    )
    with pytest.raises(LoadError) as e:
        load_project(project)
    assert len(getattr(e.value, "errors", [e.value])) >= 2


def test_yaml_syntax_error(project):
    set_dag(project, "order: [unclosed\n")
    with pytest.raises(ConfigError):
        load_project(project)

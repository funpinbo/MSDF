from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ms_dataflow.errors import DeclarationError, LoadError
from ms_dataflow.registry import collect
from ms_dataflow.registry.scan import scan_source

FIXTURES = Path(__file__).parent / "fixtures"


def write(root: Path, name: str, text: str) -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text))
    return p


def test_collects_fixture_project():
    reg = collect(FIXTURES / "calc")
    assert set(reg.services) == {"req", "src", "mid"}
    assert set(reg.actions) == {
        ("req", "on_done"),
        ("req", "on_fail"),
        ("src", "make"),
        ("mid", "add"),
        ("mid", "double"),
    }
    make = reg.action("src", "make")
    assert make and make.params == ("n",) and make.outputs == ("out",)
    assert reg.action("mid", "add").retries == 2
    assert reg.services["req"].orders == ("number",)


def test_signature_mismatch_reports_location():
    facts = scan_source(
        "svc.py",
        textwrap.dedent(
            """
            from ms_dataflow import action

            @action(inputs=["docs"])
            def fetch(q):
                return q
            """
        ),
    )
    assert len(facts.errors) == 1
    err = facts.errors[0]
    assert err.line == 5
    text = str(err)
    assert "svc.py:5" in text and "'docs'" in text and "고칠 방법" in text
    assert '@action(inputs=["docs"])' in text


def test_non_literal_option_is_error():
    facts = scan_source(
        "svc.py",
        "from ms_dataflow import action\nNAMES=['x']\n@action(inputs=NAMES)\ndef f(x): ...\n",
    )
    assert facts.errors and "리터럴" in str(facts.errors[0])


def test_aliases_are_understood():
    facts = scan_source(
        "svc.py",
        "import ms_dataflow as md\n@md.service('s')\ndef s(): md.order('o')\n"
        "@md.action(inputs=['a'])\ndef f(a): ...\n",
    )
    assert [s.name for s in facts.services] == ["s"]
    assert [a.name for a in facts.actions] == ["f"]
    assert facts.orders == [("o", 3)]


def test_action_reached_by_two_services_is_error(tmp_path):
    write(tmp_path, "shared.py", "from ms_dataflow import action\n@action\ndef common(): ...\n")
    write(
        tmp_path,
        "a.py",
        "from ms_dataflow import service\nimport shared\n@service('a')\ndef a(): ...\n",
    )
    write(
        tmp_path,
        "b.py",
        "from ms_dataflow import service\nimport shared\n@service('b')\ndef b(): ...\n",
    )
    with pytest.raises(DeclarationError) as e:
        collect(tmp_path)
    msg = str(e.value)
    assert "두 서비스" in msg and "'a'" in msg and "'b'" in msg and "shared.py" in msg


def test_plain_shared_module_is_fine(tmp_path):
    write(tmp_path, "util.py", "def clean(x): return x\n")
    write(
        tmp_path,
        "a.py",
        "from ms_dataflow import service, action\nimport util\n@service('a')\ndef a(): ...\n"
        "@action(inputs=['x'])\ndef clean(x): return util.clean(x)\n",
    )
    write(
        tmp_path,
        "b.py",
        "from ms_dataflow import service, action\nimport util\n@service('b')\ndef b(): ...\n"
        "@action(inputs=['y'])\ndef clean(y): return util.clean(y)\n",
    )
    reg = collect(tmp_path)
    assert ("a", "clean") in reg.actions and ("b", "clean") in reg.actions
    assert reg.owner_of(str(tmp_path / "util.py")) is None
    assert reg.owner_of(str(tmp_path / "a.py")) == "a"


def test_follows_function_level_and_relative_imports(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/acts.py", "from ms_dataflow import action\n@action\ndef deep(): ...\n")
    write(
        tmp_path,
        "pkg/main.py",
        "from ms_dataflow import service\n@service('m')\ndef m():\n    from . import acts\n",
    )
    reg = collect(tmp_path)
    assert ("m", "deep") in reg.actions


def test_type_checking_imports_are_skipped(tmp_path):
    write(tmp_path, "acts.py", "from ms_dataflow import action\n@action\ndef x(): ...\n")
    write(
        tmp_path,
        "main.py",
        "from typing import TYPE_CHECKING\nfrom ms_dataflow import service\n"
        "if TYPE_CHECKING:\n    import acts\n@service('m')\ndef m(): ...\n",
    )
    reg = collect(tmp_path)
    assert ("m", "x") not in reg.actions
    assert any("어느 @service에서도" in w for w in reg.warnings)


def test_dynamic_import_warns(tmp_path):
    write(
        tmp_path,
        "main.py",
        "import importlib\nfrom ms_dataflow import service\n@service('m')\ndef m():\n"
        "    importlib.import_module('x')\n",
    )
    reg = collect(tmp_path)
    assert any("동적 import" in w for w in reg.warnings)


def test_multiple_errors_are_collected(tmp_path):
    write(
        tmp_path,
        "main.py",
        "from ms_dataflow import service, action\n@service('m')\ndef m(): ...\n"
        "@action(inputs=['a'])\ndef f(b): ...\n@action(params=['p'])\ndef g(q): ...\n",
    )
    with pytest.raises(LoadError) as e:
        collect(tmp_path)
    assert len(e.value.errors) == 2  # type: ignore[attr-defined]


def test_duplicate_service_name(tmp_path):
    write(tmp_path, "a.py", "from ms_dataflow import service\n@service('x')\ndef a(): ...\n")
    write(tmp_path, "b.py", "from ms_dataflow import service\n@service('x')\ndef b(): ...\n")
    with pytest.raises(DeclarationError, match="두 번 선언"):
        collect(tmp_path)

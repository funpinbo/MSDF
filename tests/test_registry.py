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


# --- 0.2: 함수 없는 서비스 선언 ------------------------------------------------
def test_service_statement_form(tmp_path):
    write(
        tmp_path,
        "s.py",
        "from ms_dataflow import service, action\nservice('search')\n"
        "@action(outputs=['docs'])\ndef fetch() -> list:\n    return []\n",
    )
    reg = collect(tmp_path)
    assert reg.services["search"].actions == ("fetch",)


def test_service_statement_needs_literal_name(tmp_path):
    write(tmp_path, "s.py", "from ms_dataflow import service\nNAME='x'\nservice(NAME)\n")
    with pytest.raises(LoadError) as e:
        collect(tmp_path)
    assert "서비스 이름 문자열" in str(e.value.render())


def test_service_statement_runs(tmp_path):
    from ms_dataflow import service

    assert callable(service("ok"))  # 문장으로 불러도 아무 일도 없다


def test_action_in_class_is_error(tmp_path):
    write(
        tmp_path,
        "s.py",
        "from ms_dataflow import service, action\nservice('s')\n"
        "class K:\n    @action\n    def m(self): ...\n",
    )
    with pytest.raises(LoadError):
        collect(tmp_path)


# --- 0.2: 버전이 도우미 코드를 따라간다 ------------------------------------------
def _ver(tmp_path, files):
    for name, text in files.items():
        write(tmp_path, name, text)
    return collect(tmp_path).actions[("s", "a")].version


HEAD = "from ms_dataflow import service, action\nservice('s')\n"


def test_version_unchanged_without_helpers(tmp_path):
    from ms_dataflow.ids import version_of_source

    body = "@action\ndef a():\n    return len([1])\n"
    assert _ver(tmp_path, {"s.py": HEAD + body}) == version_of_source(body)


def test_version_follows_same_file_helper(tmp_path):
    v1 = _ver(
        tmp_path,
        {"s.py": HEAD + "def h(x):\n    return x + 1\n@action\ndef a():\n    return h(1)\n"},
    )
    v2 = _ver(
        tmp_path,
        {"s.py": HEAD + "def h(x):\n    return x + 2\n@action\ndef a():\n    return h(1)\n"},
    )
    v3 = _ver(
        tmp_path,
        {
            "s.py": HEAD
            + "def h(x):\n    '''doc'''\n    return x + 2  # c\n@action\ndef a():\n    return h(1)\n"
        },
    )
    assert v1 != v2
    assert v2 == v3  # 주석과 docstring은 영향 없음


def test_version_follows_constant_and_transitive(tmp_path):
    base = "def g():\n    return K\ndef h():\n    return g()\n@action\ndef a():\n    return h()\n"
    v1 = _ver(tmp_path, {"s.py": HEAD + "K = 1\n" + base})
    v2 = _ver(tmp_path, {"s.py": HEAD + "K = 2\n" + base})
    assert v1 != v2


def test_version_follows_imported_helper(tmp_path):
    files = {
        "s.py": HEAD + "from util import norm\nimport util as u\n"
        "@action\ndef a():\n    return norm(1) + u.scale(2)\n",
    }
    v1 = _ver(
        tmp_path, {**files, "util.py": "def norm(x):\n    return x\ndef scale(x):\n    return x\n"}
    )
    v2 = _ver(
        tmp_path, {**files, "util.py": "def norm(x):\n    return -x\ndef scale(x):\n    return x\n"}
    )
    v3 = _ver(
        tmp_path,
        {**files, "util.py": "def norm(x):\n    return -x\ndef scale(x):\n    return 2 * x\n"},
    )
    v4 = _ver(
        tmp_path,
        {
            **files,
            "util.py": "def norm(x):\n    return -x\ndef scale(x):\n    return 2 * x\ndef other():\n    return 0\n",
        },
    )
    assert len({v1, v2, v3}) == 3
    assert v3 == v4  # 쓰지 않는 함수는 영향 없음


def test_explicit_version_wins(tmp_path):
    v = _ver(
        tmp_path,
        {"s.py": HEAD + "def h():\n    return 1\n@action(version='7')\ndef a():\n    return h()\n"},
    )
    assert v == "7"


def test_scan_cache_reuses_and_invalidates(tmp_path, monkeypatch):
    import os

    import ms_dataflow.registry as registry

    write(tmp_path, "s.py", HEAD + "@action\ndef a():\n    return 1\n")
    cache = tmp_path / ".msdf" / "scan.cache"
    first = collect(tmp_path, cache=cache)
    assert cache.exists()
    calls = []
    real = registry.scan_source
    monkeypatch.setattr(registry, "scan_source", lambda *a: calls.append(a) or real(*a))
    assert collect(tmp_path, cache=cache).actions == first.actions
    assert calls == []  # 바뀐 파일이 없으면 분석하지 않는다
    p = tmp_path / "s.py"
    p.write_text(HEAD + "@action\ndef a():\n    return 2\n")
    os.utime(p, ns=(p.stat().st_mtime_ns + 10**9, p.stat().st_mtime_ns + 10**9))
    third = collect(tmp_path, cache=cache)
    assert len(calls) == 1
    assert third.actions[("s", "a")].version != first.actions[("s", "a")].version
    cache.write_bytes(b"broken")
    assert collect(tmp_path, cache=cache).actions == third.actions  # 깨진 캐시는 버린다

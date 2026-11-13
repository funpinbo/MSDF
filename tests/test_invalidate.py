"""0.3: invalidate() — source 데이터가 바뀌었다고 알리면 그 단계와 하위 단계가 새로 계산된다."""

from __future__ import annotations

import pytest
from conftest import clear_log, read_log

from ms_dataflow.errors import OrderError
from ms_dataflow.execute.local import LocalRunner


def events(root):
    return [e for e, _ in read_log(root)]


def run(r, n):
    r.order("number", {"n": n}, requester="req")
    r.run_until_idle()


def test_invalidate_recomputes_source_and_downstream(calc):
    with LocalRunner(calc) as r:
        run(r, 3)
        clear_log(calc)
        run(r, 3)
        assert events(calc) == ["on_done"]  # 전부 cache
        r.engine.invalidate("src", "make", {"n": 3})
        clear_log(calc)
        run(r, 3)
        assert events(calc) == ["make", "add", "double", "on_done"]


def test_params_scope_only_touches_those_params(calc):
    with LocalRunner(calc) as r:
        run(r, 3)
        run(r, 4)
        r.engine.invalidate("src", "make", {"n": 3})
        clear_log(calc)
        run(r, 4)
        assert events(calc) == ["on_done"]  # n=4는 그대로
        clear_log(calc)
        r.engine.invalidate("src", "make")  # Action 전체
        run(r, 4)
        assert events(calc)[0] == "make"


def test_same_data_version_reuses_cache(calc):
    with LocalRunner(calc) as r:
        r.engine.invalidate("src", "make", {"n": 5}, data_version="v1")
        run(r, 5)
        r.engine.invalidate("src", "make", {"n": 5}, data_version="v2")
        run(r, 5)
        r.engine.invalidate("src", "make", {"n": 5}, data_version="v1")  # 되돌림
        clear_log(calc)
        run(r, 5)
        assert events(calc) == ["on_done"]  # v1 때의 cache를 다시 씀


def test_invalidating_a_mid_dag_action(calc):
    with LocalRunner(calc) as r:
        run(r, 6)
        r.engine.invalidate("mid", "double")
        clear_log(calc)
        run(r, 6)
        assert events(calc) == ["double", "on_done"]  # 위쪽(make, add)은 cache


def test_never_invalidated_keeps_the_same_key(calc):
    from ms_dataflow import ids

    assert ids.step_key("s", "a", "v", {}, None) == ids.step_key("s", "a", "v", {}, None, None)


def test_invalidate_checks_action_and_params(calc):
    with LocalRunner(calc) as r:
        with pytest.raises(OrderError):
            r.engine.invalidate("src", "nope")
        with pytest.raises(OrderError):
            r.engine.invalidate("src", "make", {"m": 1})


def test_invalidate_from_service_code_is_limited_to_own_actions(calc):
    from ms_dataflow.decorators import invalidate as inv

    with LocalRunner(calc) as r:  # LocalRunner가 order()/invalidate()의 backend가 된다
        # src.py가 부른 것처럼: 자기 Action은 된다
        out = r.invalidate("make", {"n": 1}, None, str(calc / "src.py"))
        assert out["service"] == "src"
        # mid.py가 src의 Action을 지정하면 mid에는 그런 Action이 없다
        with pytest.raises(OrderError):
            r.invalidate("make", None, None, str(calc / "mid.py"))
        with pytest.raises(OrderError):
            inv("make")  # 테스트 파일은 어느 서비스에도 속하지 않는다

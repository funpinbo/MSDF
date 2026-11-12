"""M1 통합 테스트: 프로세스 하나에서 픽스처 DAG 실행 → 캐시 → 부분 재계산 → 재시도·실패."""

from __future__ import annotations

import pytest
from conftest import clear_log, read_log

from ms_dataflow.errors import ParamError, UnknownOrder
from ms_dataflow.execute.local import LocalRunner
from ms_dataflow.models import Settings


def events(root):
    return [e for e, _ in read_log(root)]


def test_order_roundtrip_and_cache(calc):
    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert read_log(calc) == [
            ("make", 3),
            ("add", 3),
            ("double", 4),
            ("on_done", {"value": 8}),
        ]
        run = r.engine.run(r.last.run_id)
        assert run["status"] == "done"

        clear_log(calc)
        key = r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert read_log(calc) == [("on_done", {"value": 8})]  # Action은 하나도 실행되지 않음
        assert key == r.last.lineage_key
        assert r.last.plan.cached == ["make", "add", "double"]


def test_order_from_service_code_fills_requester(calc):
    import sys

    with LocalRunner(calc) as r:
        sys.path.insert(0, str(calc))
        try:
            from ms_dataflow.decorators import resolve_function

            req = resolve_function(str(calc / "req.py"), "req")
            req(5)  # @service 함수 안에서 order() 호출
            r.run_until_idle()
        finally:
            sys.path.remove(str(calc))
        assert ("on_done", {"value": 12}) in read_log(calc)


def test_logic_change_recomputes_from_that_step(calc):
    db = calc.parent / "meta.db"
    with LocalRunner(calc, db=db) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
    mid = calc / "mid.py"
    mid.write_text(mid.read_text().replace('"value": x["value"] + 1', '"value": x["value"] + 100'))
    clear_log(calc)
    with LocalRunner(calc, db=db) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert events(calc) == ["add", "double", "on_done"]  # make는 캐시
        assert read_log(calc)[-1] == ("on_done", {"value": 206})


def test_comment_only_change_keeps_cache(calc):
    db = calc.parent / "meta.db"
    with LocalRunner(calc, db=db) as r:
        r.order("number", {"n": 1}, requester="req")
        r.run_until_idle()
    mid = calc / "mid.py"
    mid.write_text(mid.read_text().replace("def double(x):", "def double(x):  # 주석만 추가"))
    clear_log(calc)
    with LocalRunner(calc, db=db) as r:
        r.order("number", {"n": 1}, requester="req")
        r.run_until_idle()
        assert events(calc) == ["on_done"]


def test_retry_then_success(calc, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "add:2")  # 처음 2번 실패, retries=2
    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert events(calc).count("add") == 3
        assert read_log(calc)[-1] == ("on_done", {"value": 8})
        steps = r.engine.steps(r.last.run_id)
        assert steps[1]["attempts"] == 2


def test_retries_exhausted_calls_on_fail_and_cancels_downstream(calc, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "add")
    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert events(calc).count("add") == 3
        assert "double" not in events(calc)
        assert read_log(calc)[-1] == ("on_fail", "failed")
        statuses = {s["action"]: s["status"] for s in r.engine.steps(r.last.run_id)}
        assert statuses["add"] == "failed"
        assert statuses["double"] == "cancelled"
        assert r.engine.run(r.last.run_id)["status"] == "failed"
        assert "실패 주입" in r.engine.steps(r.last.run_id)[1]["error"]


def test_retry_delay_waits(calc, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "add:1")
    (calc / "mid.py").write_text(
        (calc / "mid.py").read_text().replace("retries=2)", "retries=2, retry_delay=0.2)")
    )
    import time

    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req")
        t0 = time.time()
        r.run_until_idle()
        assert time.time() - t0 >= 0.2


def test_lost_artifact_is_rebuilt(calc):
    db = calc.parent / "meta.db"
    with LocalRunner(calc, db=db) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        make_out = r.engine.steps(r.last.run_id)[0]
        import json

        aid = json.loads(make_out["outputs"])["out"]["artifact_id"]
    # 사용자 DB가 자체 정책으로 본체를 지운 상황
    store = calc / ".msdf" / "store"
    for p in store.rglob(f"{aid}*"):
        p.unlink()
    mid = calc / "mid.py"
    mid.write_text(mid.read_text().replace('"value": x["value"] + 1', '"value": x["value"] + 2'))
    clear_log(calc)
    with LocalRunner(calc, db=db) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert events(calc) == ["make", "add", "double", "on_done"]
        assert read_log(calc)[-1] == ("on_done", {"value": 10})
        assert r.engine.run(r.last.run_id)["replans"] == 1


def test_concurrent_same_order_runs_once(calc):
    with LocalRunner(calc) as r:
        r.order("number", {"n": 7}, requester="req")
        r.order("number", {"n": 7}, requester="req")
        r.run_until_idle()
        assert events(calc).count("make") == 1
        assert events(calc).count("double") == 1
        assert events(calc).count("on_done") == 2


def test_order_errors(calc):
    with LocalRunner(calc) as r:
        with pytest.raises(UnknownOrder):
            r.order("nope", {}, requester="req")
        with pytest.raises(ParamError, match="빠진 것: n"):
            r.order("number", {}, requester="req")
        with pytest.raises(ParamError, match="남는 것: z"):
            r.order("number", {"n": 1, "z": 2}, requester="req")
        with pytest.raises(UnknownOrder, match="deliveries"):
            r.order("number", {"n": 1}, requester="mid")


def test_settings_are_used(calc):
    with LocalRunner(calc, settings=Settings(lease_ttl=5)) as r:
        assert r.engine.settings.lease_ttl == 5


def test_error_shows_only_user_frames(calc, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "double")
    with LocalRunner(calc) as r:
        r.order("number", {"n": 1}, requester="req")
        r.run_until_idle()
        err = r.engine.steps(r.last.run_id)[2]["error"]
        assert "mid.py" in err and "실패 주입" in err
        assert "runner.py" not in err

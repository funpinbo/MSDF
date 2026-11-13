"""0.3: 결과가 어느 요청의 것인지 (request_id, meta, idempotency_key)."""

from __future__ import annotations

import pytest
from conftest import read_log

from ms_dataflow.errors import OrderError
from ms_dataflow.execute.local import LocalRunner

REQ = """
import json, os
from ms_dataflow import action, order, service

def log(event, value=None):
    with open(os.environ["CALC_LOG"], "a") as f:
        f.write(json.dumps({"event": event, "value": value}) + "\\n")

@service("req")
def req(n):
    return order("number", params={"n": n})

@action(inputs=["result"])
def on_done(result, meta, request_id):
    log("on_done", {"result": result, "meta": meta, "request_id": request_id})

@action
def on_fail(status, meta, error):
    log("on_fail", {"status": status, "meta": meta, "error": error})
"""


@pytest.fixture
def corr(calc):
    (calc / "req.py").write_text(REQ)
    return calc


def done(root):
    return [v for e, v in read_log(root) if e == "on_done"]


def test_meta_and_request_id_reach_the_right_delivery(corr):
    with LocalRunner(corr) as r:
        a = r.order("number", {"n": 3}, requester="req", meta={"session": "A"})
        b = r.order("number", {"n": 3}, requester="req", meta={"session": "B"})
        r.run_until_idle()
    assert a != b  # 같은 데이터, 다른 요청
    got = {d["meta"]["session"]: d for d in done(corr)}
    assert got["A"]["request_id"] == a and got["B"]["request_id"] == b
    assert got["A"]["result"] == got["B"]["result"] == {"value": 8}


def test_meta_is_not_part_of_the_cache_key(corr):
    with LocalRunner(corr) as r:
        r.order("number", {"n": 4}, requester="req", meta={"session": "A"})
        r.run_until_idle()
        r.order("number", {"n": 4}, requester="req", meta={"session": "B"})
        assert r.last.plan.steps == []  # 전부 캐시
        r.run_until_idle()
    assert [d["meta"] for d in done(corr)] == [{"session": "A"}, {"session": "B"}]


def test_delivery_without_extra_args_still_works(calc):
    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req", meta={"session": "A"})
        r.run_until_idle()
    assert ("on_done", {"value": 8}) in read_log(calc)


def test_on_fail_gets_meta_and_error(corr, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "double")
    with LocalRunner(corr) as r:
        r.order("number", {"n": 5}, requester="req", meta={"session": "C"})
        r.run_until_idle()
    fails = [v for e, v in read_log(corr) if e == "on_fail"]
    assert fails[0]["status"] == "failed" and fails[0]["meta"] == {"session": "C"}
    # 사유는 엔진이 정한 문장뿐이다. mid 서비스의 예외 문구는 넘어오지 않는다
    assert fails[0]["error"] == "결과를 만드는 중 실패했습니다"
    assert "실패 주입" not in fails[0]["error"] and "mid" not in fails[0]["error"]


def test_idempotency_key_returns_the_first_request(corr):
    with LocalRunner(corr) as r:
        a = r.order("number", {"n": 6}, requester="req", idempotency_key="q-1")
        b = r.order("number", {"n": 6}, requester="req", idempotency_key="q-1")
        assert a == b and r.last.existing
        r.run_until_idle()
        assert len(done(corr)) == 1  # 배달도 한 번
        with pytest.raises(OrderError):
            r.order("number", {"n": 7}, requester="req", idempotency_key="q-1")


def test_meta_size_limit(corr):
    with LocalRunner(corr) as r, pytest.raises(OrderError) as e:
        r.order("number", {"n": 1}, requester="req", meta={"x": "a" * 5000})
    assert "meta" in str(e.value)


def test_delete_accepts_request_id(corr):
    with LocalRunner(corr) as r:
        rid = r.order("number", {"n": 8}, requester="req")
        r.run_until_idle()
        out = r.engine.delete("req", {}, rid)
        assert len(out["deleted"]) == 1

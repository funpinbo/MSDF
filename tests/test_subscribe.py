"""0.4: subscribe — 결과가 기대는 source가 invalidate()되면 다시 계산해 다시 배달한다."""

from __future__ import annotations

import pytest
from conftest import read_log

from ms_dataflow.errors import OrderError
from ms_dataflow.execute.local import LocalRunner
from ms_dataflow.models import Settings

# source 데이터: 환경 변수 CALC_DATA가 바뀌면 make의 결과가 바뀐다
SRC = """
import json, os
from ms_dataflow import action, service

service("src")

@action(params=["n"], outputs=["out"])
def make(n):
    with open(os.environ["CALC_LOG"], "a") as f:
        f.write(json.dumps({"event": "make", "value": n}) + "\\n")
    return {"value": n + int(os.environ.get("CALC_DATA", "0"))}
"""

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
def on_done(result, meta, request_id, refresh):
    log("on_done", {"result": result["value"], "meta": meta, "id": request_id, "refresh": refresh})

@action
def on_fail(status, meta, error, refresh):
    log("on_fail", {"status": status, "meta": meta, "error": error, "refresh": refresh})
"""

FAST = Settings(refresh_min_gap=0)


@pytest.fixture
def sub(calc, monkeypatch):
    (calc / "src.py").write_text(SRC)
    (calc / "req.py").write_text(REQ)
    monkeypatch.setenv("CALC_DATA", "0")
    return calc


def delivered(root, event="on_done"):
    return [v for e, v in read_log(root) if e == event]


def makes(root):
    return [v for e, v in read_log(root) if e == "make"]


def test_change_in_source_is_delivered_again(sub, monkeypatch):
    with LocalRunner(sub, settings=FAST) as r:
        rid = r.order("number", {"n": 3}, requester="req", meta={"s": "A"}, subscribe=600)
        r.run_until_idle()
        monkeypatch.setenv("CALC_DATA", "10")  # source 데이터가 실제로 바뀜
        out = r.engine.invalidate("src", "make", {"n": 3})
        assert out["subscriptions"] == 1
        r.run_until_idle()
    first, second = delivered(sub)
    assert first == {"result": 8, "meta": {"s": "A"}, "id": rid, "refresh": 0}
    assert second == {"result": 28, "meta": {"s": "A"}, "id": rid, "refresh": 1}  # 같은 request_id


def test_unchanged_result_is_not_delivered_again(sub):
    with LocalRunner(sub, settings=FAST) as r:
        r.order("number", {"n": 3}, requester="req", subscribe=600)
        r.run_until_idle()
        r.engine.invalidate("src", "make", {"n": 3})  # 바뀌었다고 했지만 데이터는 같다
        r.run_until_idle()
        assert len(makes(sub)) == 2  # 다시 계산은 했다
        assert len(delivered(sub)) == 1  # 결과가 같아 다시 보내지 않았다
        runs = r.engine.store.query("SELECT refresh_no, status FROM run ORDER BY refresh_no")
        assert [tuple(x) for x in runs] == [(0, "done"), (1, "done")]
        skipped = r.engine.store.query("SELECT count(*) FROM step WHERE status = 'skipped'")
        assert skipped[0][0] == 1


def test_only_matching_subscriptions_wake_up(sub, monkeypatch):
    with LocalRunner(sub, settings=FAST) as r:
        r.order("number", {"n": 3}, requester="req", subscribe=600)
        r.order("number", {"n": 4}, requester="req")  # 구독하지 않음
        r.run_until_idle()
        monkeypatch.setenv("CALC_DATA", "1")
        assert r.engine.invalidate("src", "make", {"n": 5})["subscriptions"] == 0
        assert r.engine.invalidate("src", "make", {"n": 3})["subscriptions"] == 1
        r.run_until_idle()
    assert [d["result"] for d in delivered(sub)] == [8, 10, 10]  # n=3 처음, n=4, n=3 refresh


def test_whole_action_invalidation_wakes_every_scope(sub, monkeypatch):
    with LocalRunner(sub, settings=FAST) as r:
        r.order("number", {"n": 1}, requester="req", subscribe=600)
        r.order("number", {"n": 2}, requester="req", subscribe=600)
        r.run_until_idle()
        monkeypatch.setenv("CALC_DATA", "1")
        assert r.engine.invalidate("src", "make")["subscriptions"] == 2
        r.run_until_idle()
    assert sorted(d["result"] for d in delivered(sub) if d["refresh"] == 1) == [6, 8]


def test_bursts_are_coalesced(sub, monkeypatch):
    with LocalRunner(sub, settings=FAST) as r:
        r.order("number", {"n": 3}, requester="req", subscribe=600)
        r.run_until_idle()
        monkeypatch.setenv("CALC_DATA", "1")
        for _ in range(5):
            r.engine.invalidate("src", "make", {"n": 3})
        r.run_until_idle()
    assert [d["refresh"] for d in delivered(sub)] == [0, 1]  # 다섯 번 알려도 refresh는 한 번


def test_change_during_a_refresh_triggers_one_more(sub, monkeypatch):
    with LocalRunner(sub, settings=FAST) as r:
        r.order("number", {"n": 3}, requester="req", subscribe=600)
        r.run_until_idle()
        monkeypatch.setenv("CALC_DATA", "1")
        r.engine.invalidate("src", "make", {"n": 3})
        r.engine.pump()  # refresh 1 시작 (아직 실행 전)
        monkeypatch.setenv("CALC_DATA", "2")
        r.engine.invalidate("src", "make", {"n": 3})  # refresh 1이 도는 동안 또 바뀜
        r.run_until_idle()
        runs = r.engine.store.query("SELECT refresh_no FROM run ORDER BY refresh_no")
    # 변경이 refresh 1 도중에 왔으므로 refresh 2가 한 번 더 돈다
    assert [x[0] for x in runs] == [0, 1, 2]
    # refresh 1은 이미 바뀐 데이터(2)로 계산했으므로 최신 값 12를 보냈고,
    # refresh 2는 같은 결과라 다시 보내지 않는다
    assert [(d["refresh"], d["result"]) for d in delivered(sub)] == [
        (0, 8),
        (1, 12),
    ]  # (3+0+1)*2, (3+2+1)*2


def test_min_gap_spaces_refreshes(sub, monkeypatch):
    t = [1000.0]
    with LocalRunner(sub, settings=Settings(refresh_min_gap=30), sleep=False) as r:
        r.engine.clock = lambda: t[0]
        r.order("number", {"n": 3}, requester="req", subscribe=600)
        r.run_until_idle()
        monkeypatch.setenv("CALC_DATA", "1")
        r.engine.invalidate("src", "make", {"n": 3})
        r.run_until_idle()  # 첫 refresh는 바로 (last_refresh_at 없음)
        monkeypatch.setenv("CALC_DATA", "2")
        r.engine.invalidate("src", "make", {"n": 3})
        t[0] += 10
        r.run_until_idle()
        assert [d["refresh"] for d in delivered(sub)] == [0, 1]  # 30초가 안 지남
        assert r.engine.next_wakeup() == pytest.approx(1030.0)
        t[0] += 25
        r.run_until_idle()
    assert [d["refresh"] for d in delivered(sub)] == [0, 1, 2]


def test_subscription_expires(sub, monkeypatch):
    t = [1000.0]
    with LocalRunner(sub, settings=FAST, sleep=False) as r:
        r.engine.clock = lambda: t[0]
        rid = r.order("number", {"n": 3}, requester="req", subscribe=60)
        r.run_until_idle()
        t[0] += 61
        r.engine.pump()
        monkeypatch.setenv("CALC_DATA", "1")
        assert r.engine.invalidate("src", "make", {"n": 3})["subscriptions"] == 0
        [s] = r.engine.subscriptions()
        assert s["request_id"] == rid and s["status"] == "ended" and s["ended_reason"] == "expired"


def test_cancel_ends_the_subscription(sub, monkeypatch):
    with LocalRunner(sub, settings=FAST) as r:
        rid = r.order(
            "number", {"n": 3}, requester="req", subscribe=0
        )  # 0 = 만료 없음 (order(subscribe=True)와 같다)
        r.run_until_idle()
        out = r.engine.cancel(rid)
        assert out["ok"] and out["subscription_ended"]
        monkeypatch.setenv("CALC_DATA", "1")
        assert r.engine.invalidate("src", "make", {"n": 3})["subscriptions"] == 0
        r.run_until_idle()
    assert len(delivered(sub)) == 1
    assert delivered(sub, "on_fail") == []  # 이미 끝난 요청의 구독만 끝냈으니 실패 배달은 없다


def test_permission_change_ends_the_subscription_and_says_why(sub, monkeypatch):
    class Deny:
        def check_order(self, order, dag, delivery):
            return ["order: req → number"]

    with LocalRunner(sub, settings=FAST) as r:
        rid = r.order("number", {"n": 3}, requester="req", meta={"s": "A"}, subscribe=600)
        r.run_until_idle()
        r.engine.iam = Deny()  # 권한이 바뀜
        monkeypatch.setenv("CALC_DATA", "1")
        r.engine.invalidate("src", "make", {"n": 3})
        r.run_until_idle()
        [s] = r.engine.subscriptions()
        assert s["status"] == "ended" and s["ended_reason"] == "denied"
    [fail] = delivered(sub, "on_fail")
    assert fail["status"] == "cancelled" and fail["meta"] == {"s": "A"}
    assert "구독이 끝났습니다" in fail["error"] and rid


def test_service_can_cancel_only_its_own_requests(sub):
    with LocalRunner(sub, settings=FAST) as r:
        rid = r.order("number", {"n": 3}, requester="req", subscribe=600)
        r.run_until_idle()
        with pytest.raises(OrderError):
            r.cancel_request(rid, str(sub / "mid.py"))
        assert r.cancel_request(rid, str(sub / "req.py"))["subscription_ended"]


def test_subscription_limit(sub):
    with LocalRunner(sub, settings=Settings(refresh_min_gap=0, max_subscriptions=1)) as r:
        r.order("number", {"n": 1}, requester="req", subscribe=600)
        with pytest.raises(OrderError) as e:
            r.order("number", {"n": 2}, requester="req", subscribe=600)
        assert "구독" in str(e.value)


def test_order_subscribe_argument_parsing():
    from ms_dataflow.decorators import _subscribe_seconds

    assert _subscribe_seconds(None) is None and _subscribe_seconds(False) is None
    assert _subscribe_seconds(True) == 0.0
    assert _subscribe_seconds("30m") == 1800.0
    with pytest.raises(OrderError):
        _subscribe_seconds("soon")

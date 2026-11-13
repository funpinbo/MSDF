"""격리 guard: 서비스는 서로를 모른다 — 엔진이 서비스에 돌려주는 어떤 응답에도 다른 서비스가 드러나지 않는다.

요청 서비스(req)의 자리에서 엔진의 서비스용 HTTP 응답과 배달 내용을 받아 보고,
다른 서비스(src, mid)의 이름, Action, 예외 문구, DAG 경로가 섞여 있지 않은지 확인한다.
상세는 엔진 로그와 웹 UI(운영자)에서만 본다.
"""

from __future__ import annotations

import json
import re

import pytest
from _util import rule
from fastapi.testclient import TestClient

from ms_dataflow.execute.engine import FAIL_REASONS
from ms_dataflow.execute.scheduler import Scheduler
from ms_dataflow.models import Order, RegisterRequest
from ms_dataflow.project import load_project
from ms_dataflow.store import Store

# req에게 보이면 안 되는 것: 다른 서비스와 그 Action 이름, 예외 문구
OTHERS = re.compile(r"\b(src|mid|make|add|double)\b|실패 주입|Traceback")
RULE = (
    "서비스는 서로를 모른다: 엔진이 서비스에 돌려주는 응답과 배달에는 다른 서비스의 이름, Action, "
    "예외 문구, DAG 경로가 없다.",
    "요청 서비스가 그것을 알게 되면 다른 서비스가 바뀔 때 함께 깨지고, 내부 정보가 새어 나간다.",
    "서비스용 응답에는 엔진이 정한 일반 문장(FAIL_REASONS 등)만 넣고, 상세는 log.warning(엔진 로그)과 "
    "UI용 API(/api/...)에 둔다.",
)


@pytest.fixture
def sched(calc):
    s = Scheduler(load_project(calc), Store())
    return s


def register(s: Scheduler, name: str) -> str:
    reg = s.project.registry
    iid = f"inst-{name}"
    s.register(
        RegisterRequest(
            instance_id=iid,
            address="http://127.0.0.1:9",
            services=(reg.services[name],),
            actions=tuple(a for (svc, _), a in reg.actions.items() if svc == name),
        )
    )
    return iid


def order_body(iid: str) -> dict:
    return {"instance_id": iid, "requester": "req", "name": "number", "params": {"n": 1}}


def test_rejected_order_does_not_reveal_other_services(sched):
    req = register(sched, "req")
    c = TestClient(sched.app())  # lifespan을 띄우지 않는다 (가짜 주소로 단계를 보내지 않게)
    r = c.post("/order", json=order_body(req))  # src, mid가 아직 없다
    assert r.status_code == 400
    assert not OTHERS.search(r.text), rule(*RULE, r.text)

    register(sched, "src")
    register(sched, "mid")

    class Deny:
        def check_order(self, order, dag, delivery):
            return [
                "order: req → number",
                "flow: src.make → mid.add",
                "flow: mid.double → req.on_done",
            ]

    sched.engine.iam = Deny()
    r = c.post("/order", json=order_body(req))
    assert r.status_code == 400 and r.json()["code"] == "permission_denied"
    assert not OTHERS.search(r.text), rule(*RULE, r.text)


def test_failure_delivery_carries_only_engine_reasons(sched, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "double")
    from ms_dataflow.execute.runner import run_task
    from ms_dataflow.resolvers import ResolverPool

    eng, pool = sched.engine, ResolverPool()
    eng.available = None
    eng.submit(Order(name="number", params={"n": 2}, requester="req"))
    eng.submit(Order(name="number", params={"n": 2}, requester="req"))  # 합류한 두 번째 요청
    tasks = []
    while ready := eng.ready():
        for t in ready:
            eng.lease(t.run_id, t.step_no, "w")
            eng.running(t.run_id, t.step_no)
            if t.kind == "deliver_fail":
                tasks.append(t)
            spec = sched.project.registry.action(t.service, t.action)
            eng.complete(run_task(t, spec, pool))
    assert len(tasks) == 2
    for t in tasks:
        assert t.error in FAIL_REASONS.values(), rule(*RULE, t.error)
        assert not OTHERS.search(t.model_dump_json()), rule(*RULE, t.model_dump_json())


def test_invalidate_and_cancel_responses_reveal_nothing_about_others(sched):
    req, src = register(sched, "req"), register(sched, "src")
    register(sched, "mid")
    c = TestClient(sched.app())
    rid = c.post("/order", json={**order_body(req), "subscribe": 600}).json()["run_id"]

    inv = c.post(
        "/invalidate", json={"instance_id": src, "requester": "src", "action": "make"}
    ).json()
    assert set(inv) == {"version"}, rule(
        *RULE[:2],
        "서비스의 invalidate()에는 새 version만 돌려준다. 몇 개의 구독이 기대는지도 알리지 않는다.",
        inv,
    )
    can = c.post("/cancel", json={"instance_id": req, "requester": "req", "request_id": rid}).json()
    assert set(can) <= {"ok", "subscription_ended"}, rule(
        *RULE[:2],
        "서비스의 cancel()에는 성공 여부만 돌려준다. 다른 요청과 공유하던 단계 수를 알리지 않는다.",
        can,
    )
    assert not OTHERS.search(json.dumps([inv, can]))


def test_engine_reasons_never_name_anything():
    for code, text in FAIL_REASONS.items():
        assert not re.search(r"[A-Za-z_]+\.[A-Za-z_]+|→|\{", text), rule(
            *RULE[:2], "FAIL_REASONS는 이름이나 값을 끼워 넣지 않는 고정 문장이다.", (code, text)
        )

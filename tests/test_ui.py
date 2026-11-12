"""웹 UI가 읽는 JSON API와 DAG 편집기 저장 경로."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import ms_dataflow.ui as ui
from ms_dataflow.execute.runner import run_task
from ms_dataflow.execute.scheduler import Scheduler
from ms_dataflow.models import Order
from ms_dataflow.project import load_project
from ms_dataflow.resolvers import ResolverPool
from ms_dataflow.store import Store


def drain(sched: Scheduler) -> None:
    pool = ResolverPool()
    reg = sched.project.registry
    while tasks := sched.engine.ready():
        for t in tasks:
            sched.engine.lease(t.run_id, t.step_no, "w")
            sched.engine.running(t.run_id, t.step_no)
            sched.engine.complete(run_task(t, reg.action(t.service, t.action), pool))


@pytest.fixture
def sched(calc):
    s = Scheduler(load_project(calc), Store())
    ui.install(s)
    s.engine.available = None
    return s


def order(sched, n=2, requester="req"):
    sub = sched.engine.submit(Order(name="number", params={"n": n}, requester=requester))
    drain(sched)
    return sub


def test_overview_counts(sched, monkeypatch):
    order(sched, 1)
    order(sched, 1)  # 전부 캐시
    monkeypatch.setenv("CALC_FAIL", "double")
    order(sched, 5)
    with TestClient(sched.app()) as c:
        o = c.get("/api/overview").json()
    t = o["totals"]
    assert t["runs"] == 3 and t["runs_done"] == 2 and t["runs_failed"] == 1
    assert t["cache_full_hits"] == 1
    a = o["actions"]
    assert a["src.make"]["done"] == 2 and a["src.make"]["cached"] == 1
    assert a["mid.double"]["failed"] == 1 and "실패 주입" in a["mid.double"]["last_error"]
    edges = {(e["from"], e["to"], e["kind"]): e for e in o["edges"]}
    assert edges[("src.make", "mid.add", "data")]["count"] == 3  # 실행 2 + 캐시 1
    assert edges[("mid.double", "req.on_done", "delivery")]["count"] == 2
    assert edges[("mid.double", "req.on_fail", "failure")]["count"] == 1
    assert o["dags"]["number"]["runs"] == 3
    assert sum(b["done"] for b in o["timeline"]) == 5
    assert {s["name"] for s in o["services"]} == {"req", "src", "mid"}


def test_logs_filters(sched, monkeypatch):
    first = order(sched, 1)
    monkeypatch.setenv("CALC_FAIL", "double")
    order(sched, 9)
    with TestClient(sched.app()) as c:
        failed = c.get("/api/steps", params={"status": "failed"}).json()
        assert [s["action"] for s in failed] == ["double"]
        assert failed[0]["order_name"] == "number" and failed[0]["duration_ms"] is not None
        mid = c.get("/api/steps", params={"service": "mid"}).json()
        assert {s["service"] for s in mid} == {"mid"} and len(mid) == 4
        by_run = c.get("/api/steps", params={"run_id": first.run_id}).json()
        assert len(by_run) == 4
        assert c.get("/api/steps", params={"q": "실패 주입"}).json()[0]["action"] == "double"
        runs = c.get("/api/runs", params={"status": "failed"}).json()
        assert len(runs) == 1 and runs[0]["plan"]["steps"] == ["make", "add", "double"]
        detail = c.get(f"/api/runs/{first.run_id}").json()
        assert [s["step_no"] for s in detail["steps"]] == [1, 2, 3, 4]
        assert detail["dag"]["order"] == "number"
        aid = detail["steps"][2]["outputs"]["out"]["artifact_id"]
        assert c.get(f"/api/artifacts/{aid}").json()["parents"][0]["action"] == "add"
        assert c.get("/api/runs/nope").status_code == 404


def test_catalog_and_engine_log(sched):
    with TestClient(sched.app()) as c:
        cat = c.get("/api/catalog").json()
        mid = next(s for s in cat["services"] if s["name"] == "mid")
        assert [a["name"] for a in mid["actions"]] == ["add", "double"]
        assert mid["actions"][0]["inputs"] == ["x"] and mid["dags"] == ["number"]
        c.post("/unregister", json={"instance_id": "nope"})
        sched.logs.emit_message("테스트 메시지")
        events = c.get("/api/events", params={"q": "테스트"}).json()
        assert events[-1]["message"] == "테스트 메시지"


def editor_payload(order="number", result="double.out", extra_node=False):
    nodes = {
        "make": {"service": "src", "action": "make"},
        "add": {"service": "mid", "action": "add", "retries": 1},
        "double": {"service": "mid", "action": "double", "fresh_for": "1h"},
    }
    edges = [{"from": "make.out", "to": "add.x"}, {"from": "add.out", "to": "double.x"}]
    if extra_node:
        nodes["double2"] = {"service": "mid", "action": "double"}
        edges.append({"from": "double.out", "to": "double2.x"})
        result = "double2.out"
    return {
        "order": order,
        "nodes": nodes,
        "edges": edges,
        "result": result,
        "deliveries": [{"requester": "req", "on_success": "req.on_done", "on_fail": "req.on_fail"}],
        "layout": {"make": [0, 0], "add": [260, 0], "double": [520, 40.4]},
    }


def test_validate_reports_errors(sched):
    with TestClient(sched.app()) as c:
        bad = editor_payload()
        bad["edges"] = bad["edges"][:1]
        out = c.post("/api/dags/validate", json={"dag": bad, "original": "number"}).json()
        assert not out["ok"] and any("연결되어 있지 않습니다" in e for e in out["errors"])
        ok = c.post(
            "/api/dags/validate", json={"dag": editor_payload(), "original": "number"}
        ).json()
        assert ok["ok"] and "layout:" in ok["yaml"]
        dup = c.post("/api/dags/validate", json={"dag": editor_payload(), "original": None}).json()
        assert any("이미 다른 DAG" in e for e in dup["errors"])


def test_save_writes_yaml_and_reloads_engine(sched, calc):
    with TestClient(sched.app()) as c:
        out = c.put(
            "/api/dags/number", json={"dag": editor_payload(extra_node=True), "original": "number"}
        ).json()
        assert out["ok"], out
    saved = yaml.safe_load((calc / "dags" / "number.yaml").read_text())
    assert saved["result"] == "double2.out" and saved["nodes"]["double"]["fresh_for"] == "1h"
    assert saved["layout"]["double"] == [520, 40]
    load_project(calc)  # 저장한 파일은 다시 읽어도 통과한다
    sub = order(sched, 1)  # 엔진이 새 DAG로 바로 계획한다
    assert [s.node for s in sub.plan.steps] == ["make", "add", "double", "double2"]


def test_new_rename_and_delete(sched, calc):
    with TestClient(sched.app()) as c:
        out = c.put(
            "/api/dags/number2", json={"dag": editor_payload("number2"), "original": None}
        ).json()
        assert out["ok"] and (calc / "dags" / "number2.yaml").exists()
        out = c.put(
            "/api/dags/numbers", json={"dag": editor_payload("numbers"), "original": "number2"}
        ).json()
        assert out["ok"]
        assert not (calc / "dags" / "number2.yaml").exists()
        assert (calc / "dags" / "numbers.yaml").exists()
        assert {d["order"] for d in c.get("/api/dags").json()} == {"number", "numbers"}
        assert c.delete("/api/dags/numbers").json() == {"ok": True}
        assert not (calc / "dags" / "numbers.yaml").exists()
        assert c.delete("/api/dags/numbers").status_code == 404
        mismatch = c.put("/api/dags/x", json={"dag": editor_payload("y")}).json()
        assert not mismatch["ok"]


def test_ui_dist_override(sched, tmp_path, monkeypatch):
    dist = tmp_path / "elsewhere"
    dist.mkdir()
    (dist / "index.html").write_text("<p>override</p>")
    monkeypatch.setenv("MSDF_UI_DIST", str(dist))
    with TestClient(sched.app()) as c:
        assert c.get("/ui/").text == "<p>override</p>"


def test_ui_not_built_page(sched, tmp_path, monkeypatch):
    monkeypatch.delenv("MSDF_UI_DIST", raising=False)
    monkeypatch.setattr(ui, "DIST", tmp_path / "none")
    with TestClient(sched.app()) as c:
        r = c.get("/ui/")
        assert "npm run build" in r.text


def test_ui_serves_build(sched, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=app></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.delenv("MSDF_UI_DIST", raising=False)
    monkeypatch.setattr(ui, "DIST", dist)
    with TestClient(sched.app()) as c:
        assert c.get("/ui/").text == "<div id=app></div>"
        assert c.get("/ui/assets/app.js").text == "console.log(1)"
        assert c.get("/ui/logs").text == "<div id=app></div>"  # SPA 경로
        assert c.get("/ui/../../etc/passwd").status_code in (200, 404)
        assert "root:" not in c.get("/ui/..%2F..%2F..%2Fetc%2Fpasswd").text

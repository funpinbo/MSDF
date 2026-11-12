from __future__ import annotations

from fastapi.testclient import TestClient

from ms_dataflow.execute.runner import run_task
from ms_dataflow.execute.scheduler import Scheduler
from ms_dataflow.models import Order
from ms_dataflow.project import load_project
from ms_dataflow.resolvers import ResolverPool
from ms_dataflow.store import Store
from ms_dataflow.ui import install


def make(calc, fail=False):
    project = load_project(calc)
    sched = Scheduler(project, Store())
    install(sched)
    sched.engine.available = None
    sub = sched.engine.submit(Order(name="number", params={"n": 2}, requester="req"))
    pool = ResolverPool()
    while tasks := sched.engine.ready():
        for t in tasks:
            sched.engine.lease(t.run_id, t.step_no, "w")
            sched.engine.complete(run_task(t, project.registry.action(t.service, t.action), pool))
    return sched, sub


def test_ui_page_and_api(calc):
    sched, sub = make(calc)
    with TestClient(sched.app()) as c:
        assert "MSDF 엔진" in c.get("/ui").text
        dags = c.get("/api/dags").json()
        assert dags[0]["order"] == "number" and len(dags[0]["edges"]) == 2
        runs = c.get("/api/runs").json()
        assert runs[0]["run_id"] == sub.run_id and runs[0]["status"] == "done"
        detail = c.get(f"/api/runs/{sub.run_id}").json()
        assert [s["status"] for s in detail["steps"]] == ["done"] * 4
        aid = detail["steps"][2]["outputs"]["out"]["artifact_id"]
        trace = c.get(f"/api/artifacts/{aid}").json()
        assert trace["action"] == "double" and trace["parents"][0]["action"] == "add"
        assert c.get("/api/runs/nope").status_code == 404
        names = {s["name"] for s in c.get("/api/services").json()["services"]}
        assert names == {"req", "src", "mid"}


def test_ui_shows_failure(calc, monkeypatch):
    monkeypatch.setenv("CALC_FAIL", "double")
    sched, sub = make(calc)
    with TestClient(sched.app()) as c:
        steps = c.get(f"/api/runs/{sub.run_id}").json()["steps"]
        failed = [s for s in steps if s["status"] == "failed"]
        assert failed[0]["action"] == "double" and "실패 주입" in failed[0]["error"]
        assert steps[-1]["kind"] == "deliver_fail"

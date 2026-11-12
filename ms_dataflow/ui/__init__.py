"""로컬 웹 UI: DAG 보기, 실행 단계 상태, 실패 위치와 원인.

외부 의존성이 없는 정적 페이지 하나(index.html)와 읽기 전용 JSON API로 되어 있다.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from ms_dataflow import ops
from ms_dataflow.config.dag import incoming
from ms_dataflow.models import split_ref

if TYPE_CHECKING:
    from ms_dataflow.execute.scheduler import Scheduler


def _page() -> str:
    return resources.files("ms_dataflow.ui").joinpath("index.html").read_text("utf-8")


def dags_json(sched: Scheduler) -> list[dict[str, Any]]:
    reg = sched.project.registry
    out = []
    for dag in sched.project.dags.values():
        nodes = []
        for name, node in dag.nodes.items():
            spec = reg.action(node.service, node.action)
            nodes.append(
                {
                    "name": name,
                    "service": node.service,
                    "action": node.action,
                    "inputs": list(spec.inputs) if spec else [],
                    "outputs": list(spec.outputs) if spec else [],
                    "live": node.service in (sched.engine.available or set()),
                }
            )
        inc = incoming(dag)
        edges = [
            {"from": p, "from_slot": ps, "to": child, "to_slot": slot}
            for child, slots in inc.items()
            for slot, (p, ps) in slots.items()
        ]
        rn, rs = split_ref(dag.result)
        out.append(
            {
                "order": dag.order,
                "source": dag.source,
                "nodes": nodes,
                "edges": edges,
                "result": {"node": rn, "slot": rs},
                "deliveries": [d.model_dump() for d in dag.deliveries],
            }
        )
    return out


def install(sched: Scheduler) -> None:
    def routes(app: FastAPI, sched: Scheduler) -> None:
        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse("/ui")

        @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
        async def ui() -> str:
            return _page()

        @app.get("/api/dags")
        async def api_dags() -> list[dict[str, Any]]:
            return await sched.db(dags_json, sched)

        @app.get("/api/services")
        async def api_services() -> dict[str, Any]:
            reg = sched.project.registry
            return {
                "services": [
                    {
                        "name": s.name,
                        "actions": list(s.actions),
                        "orders": list(s.orders),
                        "instances": [
                            {"id": i.id, "address": i.address, "busy": bool(i.busy)}
                            for i in sched.instances.values()
                            if s.name in i.services
                        ],
                    }
                    for s in reg.services.values()
                ]
            }

        @app.get("/api/runs")
        async def api_runs(limit: int = 50) -> list[dict[str, Any]]:
            def q() -> list[dict[str, Any]]:
                rows = sched.store.query(
                    "SELECT * FROM run ORDER BY created_at DESC LIMIT ?", (min(limit, 500),)
                )
                return [dict(r) for r in rows]

            return await sched.db(q)

        @app.get("/api/runs/{run_id}")
        async def api_run(run_id: str) -> dict[str, Any]:
            def q() -> dict[str, Any] | None:
                run = sched.engine.run(run_id)
                if run is None:
                    return None
                steps = sched.engine.steps(run_id)
                for s in steps:
                    for k in ("inputs", "outputs", "params", "deps"):
                        s[k] = json.loads(s[k])
                run["params"] = json.loads(run["params"])
                run["context"] = json.loads(run["context"])
                return {"run": run, "steps": steps}

            out = await sched.db(q)
            if out is None:
                raise HTTPException(404, "run이 없습니다")
            return out

        @app.get("/api/artifacts/{artifact_id}")
        async def api_artifact(artifact_id: str) -> dict[str, Any]:
            out = await sched.db(ops.lineage, sched.engine, artifact_id)
            if not out:
                raise HTTPException(404, "artifact가 없습니다")
            return out

    sched.extensions.setdefault("routes", []).append(routes)

"""웹 UI: Vue 앱(frontend/를 빌드한 ui/dist)과 그 앱이 읽는 JSON API.

빌드 결과는 저장소에 넣지 않는다. 빌드하지 않았으면 /ui가 빌드 방법을 안내한다.

    cd frontend && npm install && npm run build
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

from ms_dataflow import dag_store, iam_store, metrics, ops
from ms_dataflow.config.dag import incoming
from ms_dataflow.errors import ConfigError
from ms_dataflow.models import split_ref

if TYPE_CHECKING:
    from ms_dataflow.execute.scheduler import Scheduler

DIST = Path(__file__).parent / "dist"

# 파일 형식을 시스템 설정에 맡기지 않는다. Windows는 레지스트리 값을 써서 .js를 text/plain으로
# 알려 주는 경우가 있는데, 그러면 브라우저가 스크립트를 실행하지 않아 화면이 비어 버린다.
MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain; charset=utf-8",
}


def dist_dir() -> Path:
    """UI 빌드 폴더. MSDF_UI_DIST(또는 msdf up --ui-dist)가 있으면 그것을 쓴다."""
    override = os.environ.get("MSDF_UI_DIST")
    return Path(override).expanduser().resolve() if override else DIST


_NOT_BUILT = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>MSDF UI 빌드 필요</title><style>body{font:15px/1.6 system-ui,sans-serif;max-width:640px;
margin:60px auto;padding:0 16px}code,pre{background:#f2f2ef;padding:2px 6px;border-radius:4px}
pre{padding:12px}</style></head><body><h1>웹 UI가 아직 빌드되지 않았습니다</h1>
<p>MSDF는 UI 소스만 배포합니다. 저장소 루트에서 한 번 빌드하면 이 주소에서 열립니다.</p>
<pre>cd frontend
npm install
npm run build</pre><p>저장소 밖에서 설치했다면(git 주소로 pip install) 빌드한 폴더를 알려 주세요:
<code>msdf up --ui-dist 경로/ms_dataflow/ui/dist</code></p>
<p>엔진은 정상 동작 중입니다. JSON API는 <code>/api/overview</code>,
<code>/api/runs</code> 등에서 볼 수 있습니다.</p></body></html>"""


def dag_json(sched: Scheduler, order: str) -> dict[str, Any]:
    dag = sched.project.dags[order]
    reg = sched.project.registry
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
                "params": list(spec.params) if spec else [],
                "fresh_for": dag_store.format_duration(node.fresh_for) if node.fresh_for else None,
                "retries": node.retries,
                "retry_delay": node.retry_delay,
                "position": list(dag.layout[name]) if name in dag.layout else None,
                "known": spec is not None,
            }
        )
    rn, rs = split_ref(dag.result)
    return {
        "order": dag.order,
        "source": dag.source,
        "nodes": nodes,
        "edges": [
            {"from": p, "from_slot": ps, "to": child, "to_slot": slot}
            for child, slots in incoming(dag).items()
            for slot, (p, ps) in slots.items()
        ],
        "result": {"node": rn, "slot": rs},
        "deliveries": [d.model_dump() for d in dag.deliveries],
        "yaml": dag_store.to_yaml(dag),
    }


def catalog(sched: Scheduler) -> dict[str, Any]:
    """편집기 팔레트와 서비스 페이지: 서비스 → Action 명세, 인스턴스."""
    reg = sched.project.registry
    now = time.time()
    used: dict[str, list[str]] = {}
    for dag in sched.project.dags.values():
        for n in dag.nodes.values():
            used.setdefault(n.service, [])
            if dag.order not in used[n.service]:
                used[n.service].append(dag.order)
        for d in dag.deliveries:
            used.setdefault(d.requester, [])
            if dag.order not in used[d.requester]:
                used[d.requester].append(dag.order)
    services = []
    names = sorted(set(reg.services) | {s for i in sched.instances.values() for s in i.services})
    for name in names:
        spec = reg.services.get(name)
        actions = [
            {
                "name": a.name,
                "inputs": list(a.inputs),
                "outputs": list(a.outputs),
                "params": list(a.params),
                "version": a.version,
                "retries": a.retries,
                "fresh_for": dag_store.format_duration(a.fresh_for) if a.fresh_for else None,
                "file": a.file,
                "line": a.lineno,
            }
            for (svc, _), a in sorted(reg.actions.items())
            if svc == name
        ]
        services.append(
            {
                "name": name,
                "file": spec.file if spec else None,
                "orders": list(spec.orders) if spec else [],
                "dags": sorted(used.get(name, [])),
                "actions": actions,
                "instances": [
                    {
                        "id": i.id,
                        "address": i.address,
                        "busy": list(i.busy) if i.busy else None,
                        "last_seen_s": round(now - i.last_seen, 1),
                        "up_s": round(now - i.registered_at, 1),
                    }
                    for i in sched.instances.values()
                    if name in i.services
                ],
            }
        )
    return {"services": services, "strict": sched.project.strict_services}


def install(sched: Scheduler, *, pages: bool = True) -> None:
    """JSON API(/api/...)는 항상 단다. CLI(msdf status, runs, cancel)도 이것을 쓴다.

    pages=False(msdf up --no-ui)면 웹 화면(/ui)만 뺀다.
    """

    def routes(app: FastAPI, sched: Scheduler) -> None:
        if pages:
            _pages(app)
        _api(app, sched)

    def _pages(app: FastAPI) -> None:
        # --- 정적 파일 -------------------------------------------------------
        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse("/ui/")

        @app.get("/ui", include_in_schema=False)
        async def ui_root() -> RedirectResponse:
            return RedirectResponse("/ui/")

        @app.get("/ui/{path:path}", include_in_schema=False, response_model=None)
        async def ui(path: str) -> FileResponse | HTMLResponse:
            dist = dist_dir()
            index = dist / "index.html"
            if not index.exists():
                return HTMLResponse(_NOT_BUILT)
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target, media_type=MEDIA_TYPES.get(target.suffix.lower()))
            # 해시 라우팅이라 나머지는 index.html
            return FileResponse(index, media_type=MEDIA_TYPES[".html"])

    def _api(app: FastAPI, sched: Scheduler) -> None:
        # --- 맵 --------------------------------------------------------------
        @app.get("/api/overview")
        async def api_overview(window: float = 3600) -> dict[str, Any]:
            data = await sched.db(metrics.overview, sched.store, sched.project.dags, window, None)
            data["services"] = (await sched.db(catalog, sched))["services"]
            return data

        @app.get("/api/catalog")
        async def api_catalog() -> dict[str, Any]:
            return await sched.db(catalog, sched)

        # --- DAG -------------------------------------------------------------
        @app.get("/api/dags")
        async def api_dags() -> list[dict[str, Any]]:
            def q() -> list[dict[str, Any]]:
                return [dag_json(sched, o) for o in sorted(sched.project.dags)]

            return await sched.db(q)

        @app.get("/api/dags/{order}")
        async def api_dag(order: str) -> dict[str, Any]:
            if order not in sched.project.dags:
                raise HTTPException(404, "DAG가 없습니다")
            return await sched.db(dag_json, sched, order)

        @app.post("/api/dags/validate")
        async def api_validate(body: dict[str, Any]) -> dict[str, Any]:
            def q() -> dict[str, Any]:
                dag, errors, warnings = dag_store.check(
                    sched.project, body.get("dag", {}), body.get("original")
                )
                return {
                    "ok": not errors,
                    "errors": errors,
                    "warnings": warnings,
                    "yaml": dag_store.to_yaml(dag) if dag else None,
                }

            return await sched.db(q)

        @app.put("/api/dags/{order}")
        async def api_save(order: str, body: dict[str, Any]) -> dict[str, Any]:
            def q() -> dict[str, Any]:
                original = body.get("original") or None
                dag, errors, warnings = dag_store.check(
                    sched.project, body.get("dag", {}), original
                )
                if dag is None or errors:
                    return {"ok": False, "errors": errors, "warnings": warnings}
                if dag.order != order:
                    return {
                        "ok": False,
                        "errors": ["주소의 order 이름과 내용이 다릅니다."],
                        "warnings": warnings,
                    }
                try:
                    path = dag_store.save(sched.project, dag, original)
                except ConfigError as e:
                    return {"ok": False, "errors": [e.reason], "warnings": warnings}
                return {
                    "ok": True,
                    "path": path,
                    "warnings": warnings,
                    "dag": dag_json(sched, dag.order),
                }

            out = await sched.db(q)
            if out["ok"]:
                sched.logs.emit_message(f"DAG 저장: {order} → {out['path']}")
            return out

        @app.delete("/api/dags/{order}")
        async def api_delete_dag(order: str) -> dict[str, bool]:
            try:
                await sched.db(dag_store.remove, sched.project, order)
            except ConfigError as e:
                raise HTTPException(404, e.reason) from None
            sched.logs.emit_message(f"DAG 삭제: {order}")
            return {"ok": True}

        # --- 로그 ------------------------------------------------------------
        @app.get("/api/runs")
        async def api_runs(
            order: str | None = None,
            requester: str | None = None,
            status: str | None = None,
            limit: int = 100,
            before: float | None = None,
        ) -> list[dict[str, Any]]:
            return await sched.db(
                lambda: metrics.runs_log(
                    sched.store,
                    order=order,
                    requester=requester,
                    status=status,
                    limit=limit,
                    before=before,
                )
            )

        @app.get("/api/runs/{run_id}")
        async def api_run(run_id: str) -> dict[str, Any]:
            def q() -> dict[str, Any] | None:
                run = metrics.runs_log(sched.store, run_id=run_id, limit=1)
                if not run:
                    return None
                steps = metrics.steps_log(sched.store, run_id=run_id, limit=1000)
                steps.sort(key=lambda s: s["step_no"])
                order = run[0]["order_name"]
                dag = dag_json(sched, order) if order in sched.project.dags else None
                sid = run[0].get("subscription_id")
                sub = next(
                    (s for s in sched.engine.subscriptions() if s["request_id"] == sid), None
                )
                return {"run": run[0], "steps": steps, "dag": dag, "subscription": sub}

            out = await sched.db(q)
            if out is None:
                raise HTTPException(404, "run이 없습니다")
            return out

        @app.get("/api/steps")
        async def api_steps(
            service: str | None = None,
            order: str | None = None,
            status: str | None = None,
            run_id: str | None = None,
            q: str | None = None,
            limit: int = 100,
            before: float | None = None,
        ) -> list[dict[str, Any]]:
            return await sched.db(
                lambda: metrics.steps_log(
                    sched.store,
                    service=service,
                    order=order,
                    status=status,
                    run_id=run_id,
                    q=q,
                    limit=limit,
                    before=before,
                )
            )

        @app.get("/api/events")
        async def api_events(
            after: int = 0, q: str | None = None, level: str | None = None, limit: int = 500
        ) -> list[dict[str, Any]]:
            return sched.logs.query(after=after, q=q, level=level, limit=limit)

        @app.get("/api/artifacts/{artifact_id}")
        async def api_artifact(artifact_id: str) -> dict[str, Any]:
            out = await sched.db(ops.lineage, sched.engine, artifact_id)
            if not out:
                raise HTTPException(404, "artifact가 없습니다")
            return out

        @app.get("/api/services")
        async def api_services() -> dict[str, Any]:
            return await sched.db(catalog, sched)

        # --- 실시간 신호 (SSE) -------------------------------------------------
        @app.get("/api/stream")
        async def api_stream(request: Request, once: bool = False) -> StreamingResponse:
            """상태가 바뀌면 신호를 보낸다. 화면은 신호를 받을 때만 다시 읽는다."""

            async def gen() -> Any:
                yield "retry: 3000\n\n"
                last: tuple[int, int] | None = None
                quiet = 0
                while True:
                    sig = (sched.version, sched.logs.seq)
                    if sig != last:
                        last = sig
                        quiet = 0
                        yield f"data: {json.dumps({'v': sig[0], 'log': sig[1]})}\n\n"
                        if once:
                            return
                    else:
                        quiet += 1
                        if quiet >= 50:  # 15초마다 연결 유지용 주석
                            quiet = 0
                            yield ": ping\n\n"
                    if await request.is_disconnected():
                        return
                    await asyncio.sleep(0.3)

            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # --- 구독 -------------------------------------------------------------
        @app.get("/api/subscriptions")
        async def api_subscriptions(status: str | None = None) -> list[dict[str, Any]]:
            return await sched.db(sched.engine.subscriptions, status)

        # --- 실행 취소 ---------------------------------------------------------
        @app.post("/api/runs/{run_id}/cancel")
        async def api_cancel(run_id: str) -> dict[str, Any]:
            try:
                out: dict[str, Any] = await sched.db(sched.engine.cancel, run_id)
            except KeyError:
                raise HTTPException(404, "run이 없습니다") from None
            if out["ok"]:
                sched.logs.emit_message(f"실행 취소: {run_id} (단계 {out['cancelled']}개 중지)")
            sched.kick()
            return out

        # --- IAM -------------------------------------------------------------
        @app.get("/api/iam")
        async def api_iam() -> dict[str, Any]:
            def q() -> dict[str, Any]:
                iam = sched.project.iam
                spec = iam.spec if iam else None
                data = iam_store.to_json(spec)
                path = iam_store.iam_path(sched.project)
                return {
                    **data,
                    "exists": iam is not None,
                    "path": str(path),
                    "yaml": path.read_text("utf-8") if path.exists() else "",
                    "required_context": iam.required_context() if iam else [],
                    "services": sorted(sched.project.registry.services),
                    "actions": sorted(f"{s}.{a}" for s, a in sched.project.registry.actions),
                    "orders": sorted(sched.project.dags),
                }

            return await sched.db(q)

        @app.post("/api/iam/validate")
        async def api_iam_validate(body: dict[str, Any]) -> dict[str, Any]:
            def q() -> dict[str, Any]:
                spec, raw, errors = iam_store.check(sched.project, body)
                return {
                    "ok": spec is not None and not errors,
                    "errors": errors,
                    "yaml": iam_store.to_yaml(raw),
                }

            return await sched.db(q)

        @app.put("/api/iam")
        async def api_iam_save(body: dict[str, Any]) -> dict[str, Any]:
            def q() -> dict[str, Any]:
                spec, raw, errors = iam_store.check(sched.project, body)
                if spec is None or errors:
                    return {"ok": False, "errors": errors}
                path = iam_store.save(sched.project, spec, raw, sched.engine)
                return {"ok": True, "path": path, "yaml": iam_store.to_yaml(raw)}

            out = await sched.db(q)
            if out["ok"]:
                sched.logs.emit_message(f"IAM 저장: {out['path']}")
                sched.kick()
            return out

        @app.post("/api/iam/try")
        async def api_iam_try(body: dict[str, Any]) -> dict[str, Any]:
            def q() -> dict[str, Any]:
                ctx = {str(k): str(v) for k, v in (body.get("context") or {}).items() if v}
                return iam_store.try_order(
                    sched.project, str(body.get("order", "")), str(body.get("requester", "")), ctx
                )

            try:
                return await sched.db(q)
            except ConfigError as e:
                raise HTTPException(404, e.reason) from None

    sched.extensions.setdefault("routes", []).append(routes)

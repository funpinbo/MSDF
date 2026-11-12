"""Scheduler: 엔진 프로세스(msdf up)의 HTTP 서버.

- 모든 DB 작업은 전용 스레드 하나에서 한다(유일한 작성자).
- 쉬는 서비스 인스턴스에 단계를 밀어준다(push). 서비스가 큐를 직접 읽지 않는다.
- lease가 만료되면 단계를 되돌리고, 심박이 끊긴 인스턴스는 정리한다.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ms_dataflow.errors import OrderError, PermissionDenied, ServiceUnavailable
from ms_dataflow.execute.engine import Engine
from ms_dataflow.metrics import LogBuffer
from ms_dataflow.models import (
    DeleteRequest,
    Order,
    OrderRequest,
    OrderResponse,
    RegisterRequest,
    RegisterResponse,
    ResultReport,
    Settings,
    StepTask,
)
from ms_dataflow.project import Project
from ms_dataflow.registry import Registry
from ms_dataflow.store import Store

log = logging.getLogger("msdf.scheduler")
T = TypeVar("T")


def token_ok(request: Any, token: str) -> bool:
    """Authorization: Bearer, X-MSDF-Token 헤더, 또는 ?token= (EventSource용) 중 하나."""
    got = request.headers.get("x-msdf-token") or ""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        got = auth[7:].strip()
    got = got or request.query_params.get("token") or ""
    return hmac.compare_digest(got.encode(), token.encode())


@dataclass
class Instance:
    id: str
    address: str
    services: set[str]
    actions: dict[tuple[str, str], Any]
    last_seen: float
    busy: tuple[str, int] | None = None
    sent_at: float = 0.0
    context_keys: tuple[str, ...] | None = None
    registered_at: float = 0.0


@dataclass
class Scheduler:
    project: Project
    store: Store
    settings: Settings = field(default_factory=Settings)
    token: str | None = None  # 있으면 모든 API(서비스·UI)가 이 값을 보내야 한다

    def __post_init__(self) -> None:
        self.engine = Engine(
            self.store,
            self.project.registry,
            self.project.dags,
            self.project.resolvers,
            iam=self.project.iam,
            settings=self.settings,
        )
        self.engine.available = set()
        self.instances: dict[str, Instance] = {}
        self._db = ThreadPoolExecutor(max_workers=1, thread_name_prefix="msdf-db")
        self._wake: asyncio.Event | None = None
        self._http: httpx.AsyncClient | None = None
        self._rr = 0
        self.extensions: dict[str, Any] = {}
        self.logs = LogBuffer()
        self.version = 0  # 상태가 바뀔 때마다 오른다. UI 스트림(SSE)이 본다

    # --- 공통 ---------------------------------------------------------------
    async def db(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._db, fn, *args)

    def kick(self) -> None:
        self.version += 1
        if self._wake is not None:
            self._wake.set()

    def _refresh_available(self) -> None:
        live: set[str] = set()
        for inst in self.instances.values():
            live |= inst.services
        self.engine.available = live

    # --- 등록 ---------------------------------------------------------------
    def register(self, req: RegisterRequest) -> RegisterResponse:
        warnings: list[str] = []
        for svc in req.services:
            for other in self.instances.values():
                if other.id == req.instance_id or svc.name not in other.services:
                    continue
                mine = {(a.name, a.version) for a in req.actions if a.service == svc.name}
                theirs = {(k[1], v.version) for k, v in other.actions.items() if k[0] == svc.name}
                if mine != theirs:
                    raise HTTPException(
                        409,
                        {
                            "code": "registration_error",
                            "message": f"서비스 '{svc.name}'이 다른 코드로 이미 등록되어 있습니다 "
                            f"(인스턴스 {other.id}, {other.address}). 같은 이름의 서비스는 같은 "
                            "코드여야 합니다. 옛 인스턴스를 종료하고 다시 시작하세요.",
                        },
                    )
        iam = self.project.iam
        if iam is not None:
            missing = iam.missing_context_keys(req.context_keys)
            if missing:
                raise HTTPException(
                    409,
                    {
                        "code": "registration_error",
                        "message": "@context가 IAM 계층 값을 돌려주지 않습니다: "
                        + ", ".join(missing)
                        + ". @context 함수의 반환 키를 iam.yaml의 layers와 맞추세요.",
                    },
                )
        incoming = Registry(root=self.project.registry.root)
        for s in req.services:
            incoming.services[s.name] = s
        for a in req.actions:
            incoming.actions[(a.service, a.name)] = a
        self.project.registry.merge(incoming)
        for dag in self.project.dags.values():
            for name, node in dag.nodes.items():
                if (
                    node.service in incoming.services
                    and incoming.action(node.service, node.action) is None
                ):
                    warnings.append(
                        f"DAG '{dag.order}' 노드 '{name}': 등록된 서비스 '{node.service}'에 "
                        f"Action '{node.action}'이 없습니다."
                    )
        self.instances[req.instance_id] = Instance(
            id=req.instance_id,
            address=req.address.rstrip("/"),
            services={s.name for s in req.services},
            actions=dict(incoming.actions),
            last_seen=time.time(),
            context_keys=req.context_keys,
            registered_at=time.time(),
        )
        self._refresh_available()
        for w in warnings:
            log.warning(w)
        log.info(
            "등록: %s %s (%s)",
            ",".join(sorted(s.name for s in req.services)),
            req.address,
            req.instance_id,
        )
        self.kick()
        return RegisterResponse(
            instance_id=req.instance_id, settings=self.settings, warnings=tuple(warnings)
        )

    def drop(self, instance_id: str) -> None:
        inst = self.instances.pop(instance_id, None)
        if inst is not None:
            self.version += 1
            log.info("해제: %s", instance_id)
            self._refresh_available()

    # --- 배정 ---------------------------------------------------------------
    def _pick(self, service: str) -> Instance | None:
        idle = [i for i in self.instances.values() if service in i.services and i.busy is None]
        if not idle:
            return None
        self._rr += 1
        return idle[self._rr % len(idle)]

    async def dispatch_once(self) -> int:
        idle_services = {s for i in self.instances.values() if i.busy is None for s in i.services}
        if not idle_services:
            return 0
        tasks: list[StepTask] = await self.db(self.engine.ready, None, idle_services)
        sent = 0
        for task in tasks:
            inst = self._pick(task.service)
            if inst is None:
                continue
            if not await self.db(self.engine.lease, task.run_id, task.step_no, inst.id):
                continue
            inst.busy = (task.run_id, task.step_no)
            inst.sent_at = time.time()
            # 서비스가 아주 빨리 결과를 보고할 수 있으므로 보내기 전에 running으로 둔다
            await self.db(self.engine.running, task.run_id, task.step_no)
            log.info(
                "실행: %s:%s %s.%s → %s",
                task.run_id,
                task.step_no,
                task.service,
                task.action,
                inst.id,
            )
            assert self._http is not None
            try:
                resp = await self._http.post(
                    f"{inst.address}/run", content=task.model_dump_json(), timeout=10.0
                )
                ok = resp.status_code == 202
            except httpx.HTTPError as e:
                log.warning("단계 전송 실패 → 인스턴스 정리: %s (%s)", inst.id, e)
                ok = False
                self.drop(inst.id)
            if ok:
                sent += 1
            else:
                inst.busy = None
                await self.db(self.engine.release, task.run_id, task.step_no)
        return sent

    async def dispatch_loop(self) -> None:
        assert self._wake is not None
        while True:
            self._wake.clear()
            try:
                await self.dispatch_once()
            except Exception:  # noqa: BLE001
                log.exception("dispatch 오류")
            wake = await self.db(self.engine.next_wakeup, None)
            timeout = 1.0 if wake is None else max(0.01, min(1.0, wake - time.time()))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout)

    async def reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.reaper_every)
            await self.reap_once()

    async def reap_once(self) -> None:
        now = time.time()
        for inst in list(self.instances.values()):
            if now - inst.last_seen > self.settings.lease_ttl:
                log.warning("심박 끊김 → 인스턴스 정리: %s", inst.id)
                self.drop(inst.id)
                await self.db(self.engine.release_worker, inst.id)
        await self.db(self.engine.purge)
        n = await self.db(self.engine.reap, None)
        if n:
            log.warning("lease 만료 → %d개 단계 재큐잉", n)
            self.kick()

    # --- 앱 -----------------------------------------------------------------
    def app(self) -> FastAPI:
        sched = self

        async def lifespan(app: FastAPI) -> Any:
            msdf_log = logging.getLogger("msdf")
            msdf_log.addHandler(sched.logs)
            if msdf_log.level == logging.NOTSET or msdf_log.level > logging.INFO:
                msdf_log.setLevel(logging.INFO)
            sched._wake = asyncio.Event()
            headers = {"Content-Type": "application/json"}
            if sched.token:
                headers["Authorization"] = f"Bearer {sched.token}"
            sched._http = httpx.AsyncClient(headers=headers)
            async with asyncio.TaskGroup() as tg:
                loops = [tg.create_task(sched.dispatch_loop()), tg.create_task(sched.reaper_loop())]
                try:
                    yield
                finally:
                    for t in loops:
                        t.cancel()
            await sched._http.aclose()
            msdf_log.removeHandler(sched.logs)

        app = FastAPI(title="MSDF", lifespan=lifespan)
        app.state.sched = sched

        @app.middleware("http")
        async def auth(request: Request, call_next: Any) -> Response:
            path = request.url.path
            public = path in ("/", "/ui", "/health") or path.startswith("/ui/")
            if sched.token and not public and not token_ok(request, sched.token):
                return JSONResponse(
                    {"detail": {"code": "unauthorized", "message": "엔진 토큰이 필요합니다"}},
                    status_code=401,
                )
            resp: Response = await call_next(request)
            return resp

        @app.exception_handler(OrderError)
        async def order_error(_: Any, exc: OrderError) -> JSONResponse:
            body: dict[str, Any] = {"code": exc.code, "message": str(exc)}
            if isinstance(exc, PermissionDenied):
                body["blocked"] = exc.blocked
            if isinstance(exc, ServiceUnavailable):
                body["missing"] = exc.missing
            return JSONResponse(body, status_code=400)

        @app.post("/register")
        async def register(req: RegisterRequest) -> RegisterResponse:
            # 레지스트리를 바꾸므로 DB 스레드에서 한다 (엔진이 같은 스레드에서 읽는다)
            return await sched.db(sched.register, req)

        @app.post("/unregister")
        async def unregister(body: dict[str, str]) -> dict[str, bool]:
            iid = body.get("instance_id", "")
            sched.drop(iid)
            await sched.db(sched.engine.release_worker, iid)
            sched.kick()
            return {"ok": True}

        @app.post("/heartbeat")
        async def heartbeat(body: dict[str, str]) -> dict[str, bool]:
            inst = sched.instances.get(body.get("instance_id", ""))
            if inst is None:
                return {"known": False}
            inst.last_seen = time.time()
            await sched.db(sched.engine.heartbeat, inst.id, None)
            return {"known": True}

        @app.post("/order")
        async def order(req: OrderRequest) -> OrderResponse:
            inst = sched.instances.get(req.instance_id)
            if inst is None or req.requester not in inst.services:
                raise HTTPException(
                    403,
                    {
                        "code": "order_error",
                        "message": "등록되지 않은 인스턴스이거나, 이 인스턴스의 서비스가 아닙니다.",
                    },
                )
            o = Order(
                name=req.name, params=req.params, requester=req.requester, context=req.context
            )
            submitted = await sched.db(sched.engine.submit, o)
            sched.kick()
            log.info("order: %s by %s → run %s", req.name, req.requester, submitted.run_id)
            return OrderResponse(run_id=submitted.run_id, lineage_key=submitted.lineage_key)

        @app.post("/step/result")
        async def result(rep: ResultReport) -> dict[str, bool]:
            inst = sched.instances.get(rep.instance_id)
            if inst is not None:
                inst.busy = None
                inst.last_seen = time.time()
            await sched.db(sched.engine.complete, rep.result, None)
            r = rep.result
            if r.ok:
                log.info("성공: %s:%s", r.run_id, r.step_no)
            else:
                why = {"action": "Action 예외", "lost": "입력 데이터 유실", "other": "실행 오류"}
                last = (r.error or "").strip().splitlines()[-1:] or [""]
                log.warning(
                    "실패(%s): %s:%s %s",
                    why.get(r.error_kind or "", r.error_kind),
                    r.run_id,
                    r.step_no,
                    last[0][:200],
                )
            sched.kick()
            return {"ok": True}

        @app.post("/delete")
        async def delete(req: DeleteRequest) -> dict[str, Any]:
            inst = sched.instances.get(req.instance_id)
            if inst is None or req.requester not in inst.services:
                raise HTTPException(
                    403, {"code": "order_error", "message": "등록되지 않은 인스턴스"}
                )
            out: dict[str, Any] = await sched.db(
                sched.engine.delete, req.requester, req.context, req.lineage_key, req.cascade
            )
            return out

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {
                "ok": True,
                "instances": [
                    {
                        "id": i.id,
                        "address": i.address,
                        "services": sorted(i.services),
                        "busy": list(i.busy) if i.busy else None,
                    }
                    for i in sched.instances.values()
                ],
            }

        for setup in sched.extensions.get("routes", []):
            setup(app, sched)
        return app

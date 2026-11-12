"""start(): 이 프로세스를 엔진에 붙인다. order()가 엔진으로 가는 길도 여기서 만든다."""

from __future__ import annotations

import atexit
import contextlib
import inspect
import logging
import os
import signal
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # 묶음 없이 설치한 경우. 데코레이터와 msdf check는 httpx 없이 동작해야 한다
    httpx = None  # type: ignore[assignment]

from ms_dataflow.decorators import context_declared, current_context, set_backend
from ms_dataflow.errors import ORDER_ERRORS, OrderError, RegistrationError
from ms_dataflow.models import (
    DeleteRequest,
    OrderRequest,
    RegisterRequest,
    RegisterResponse,
    ResultReport,
    Settings,
    StepResult,
)
from ms_dataflow.registry import Registry, collect

log = logging.getLogger("msdf.client")

DEFAULT_SCHEDULER = "http://127.0.0.1:8787"


def _raise_order_error(resp: httpx.Response) -> None:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    detail = body.get("detail", body)
    if not isinstance(detail, dict):
        detail = {"message": str(detail)}
    cls = ORDER_ERRORS.get(str(detail.get("code")), OrderError)
    message = str(detail.get("message", resp.text))
    if "blocked" in detail:
        raise cls(message, detail["blocked"])
    if "missing" in detail:
        raise cls(message, detail["missing"])
    raise cls(message)


class Client:
    """서비스 프로세스 하나의 엔진 연결."""

    def __init__(
        self,
        registry: Registry,
        scheduler: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        token: str | None = None,
    ) -> None:
        self.registry = registry
        self.token = token
        self.scheduler = scheduler.rstrip("/")
        self.instance_id = uuid.uuid4().hex[:12]
        self.settings = Settings()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(timeout=10.0, headers=headers)
        self.host = host
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self.port = self._sock.getsockname()[1]
        self.address = f"http://{host}:{self.port}"
        self._stop = threading.Event()
        self.registered = threading.Event()
        self._server: Any = None

    # --- 수신 서버 ----------------------------------------------------------
    def serve(self) -> None:
        import uvicorn

        from ms_dataflow.execute.worker import Worker

        self.worker = Worker(self.registry, self.report, lambda: self.instance_id, self.token)
        config = uvicorn.Config(self.worker.app(), log_level="warning", lifespan="off")
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None  # 사용자 앱의 시그널을 건드리지 않는다
        t = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [self._sock]},
            daemon=True,
            name="msdf-worker",
        )
        t.start()
        for _ in range(200):
            if self._server.started:
                return
            time.sleep(0.01)

    # --- 등록과 심박 ----------------------------------------------------------
    def _register_request(self) -> RegisterRequest:
        keys: tuple[str, ...] | None = None
        if context_declared():
            try:
                keys = tuple(current_context())
            except Exception as e:  # noqa: BLE001 - 요청 밖에서는 값을 못 만들 수 있다
                log.warning("MSDF: 등록 시 @context를 부르지 못해 키 검사를 건너뜁니다: %s", e)
        return RegisterRequest(
            instance_id=self.instance_id,
            address=self.address,
            services=tuple(self.registry.services.values()),
            actions=tuple(self.registry.actions.values()),
            context_keys=keys,
        )

    def register_once(self) -> bool:
        try:
            resp = self.http.post(
                f"{self.scheduler}/register", content=self._register_request().model_dump_json()
            )
        except httpx.HTTPError:
            return False
        if resp.status_code == 401:
            raise RegistrationError(
                "엔진이 토큰을 요구합니다. 엔진과 같은 값을 MSDF_TOKEN 환경 변수나 "
                "start(token=...)로 주세요."
            )
        if resp.status_code == 409:
            detail = resp.json().get("detail", {})
            raise RegistrationError(str(detail.get("message", resp.text)))
        resp.raise_for_status()
        reg = RegisterResponse.model_validate(resp.json())
        self.settings = reg.settings
        for w in reg.warnings:
            log.warning("MSDF: %s", w)
        self.registered.set()
        return True

    def heartbeat_loop(self) -> None:
        failures = 0
        while not self._stop.wait(self.settings.heartbeat_every):
            try:
                resp = self.http.post(
                    f"{self.scheduler}/heartbeat", json={"instance_id": self.instance_id}
                )
                if not resp.json().get("known", False):
                    self.registered.clear()
                    self.register_once()
                failures = 0
            except (httpx.HTTPError, ValueError):
                failures += 1
                if failures == 3:
                    log.warning("MSDF: 엔진에 심박을 보내지 못하고 있습니다 (%s)", self.scheduler)
                if not self.registered.is_set():
                    self._try_register_quietly()
            except RegistrationError as e:
                log.error("MSDF: %s", e)

    def _try_register_quietly(self) -> None:
        try:
            self.register_once()
        except RegistrationError as e:
            log.error("MSDF: %s", e)

    def report(self, result: StepResult) -> None:
        rep = ResultReport(instance_id=self.instance_id, result=result)
        resp = self.http.post(f"{self.scheduler}/step/result", content=rep.model_dump_json())
        resp.raise_for_status()

    # --- order -------------------------------------------------------------
    def _requester(self, caller_file: str) -> str:
        owner = self.registry.owner_of(caller_file)
        if owner is None:
            if len(self.registry.services) == 1:
                return next(iter(self.registry.services))
            raise OrderError(
                f"{caller_file}이 어느 서비스에 속하는지 알 수 없습니다. "
                "order()는 @service에서 import로 닿는 파일에서 호출하세요."
            )
        return owner

    def submit(self, name: str, params: dict[str, Any], caller_file: str) -> str:
        req = OrderRequest(
            instance_id=self.instance_id,
            requester=self._requester(caller_file),
            name=name,
            params=params,
            context=current_context(),
        )
        try:
            resp = self.http.post(f"{self.scheduler}/order", content=req.model_dump_json())
        except httpx.HTTPError as e:
            raise OrderError(f"엔진에 연결할 수 없습니다 ({self.scheduler}): {e}") from None
        if resp.status_code != 200:
            _raise_order_error(resp)
        return str(resp.json()["lineage_key"])

    def delete(self, key: str, cascade: bool, caller_file: str) -> dict[str, Any]:
        req = DeleteRequest(
            instance_id=self.instance_id,
            requester=self._requester(caller_file),
            lineage_key=key,
            cascade=cascade,
            context=current_context(),
        )
        try:
            resp = self.http.post(f"{self.scheduler}/delete", content=req.model_dump_json())
        except httpx.HTTPError as e:
            raise OrderError(f"엔진에 연결할 수 없습니다 ({self.scheduler}): {e}") from None
        if resp.status_code != 200:
            _raise_order_error(resp)
        out: dict[str, Any] = resp.json()
        return out

    # --- 종료 --------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(httpx.HTTPError):
            self.http.post(
                f"{self.scheduler}/unregister", json={"instance_id": self.instance_id}, timeout=2.0
            )
        if self._server is not None:
            self._server.should_exit = True
        self.http.close()


_CLIENT: list[Client] = []


def _require_runtime() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        missing = True
    else:
        missing = httpx is None
    if missing:
        raise ImportError(
            "start()에는 runtime 묶음이 필요합니다. "
            'pip install "msdf[runtime]" (저장소에서는 uv sync --all-extras)로 설치하세요.'
        )


def _caller_file() -> str:
    for frame in inspect.stack()[2:]:
        f = frame.filename
        if not f.startswith("<") and "ms_dataflow" not in Path(f).parts:
            return os.path.realpath(f)
    return os.path.realpath(os.path.join(os.getcwd(), "__main__.py"))


def start(
    scheduler: str | None = None,
    port: int = 0,
    *,
    required: bool = True,
    host: str = "127.0.0.1",
    root: str | None = None,
    timeout: float | None = None,
    block: bool = False,
    token: str | None = None,
) -> None:
    """이 프로세스를 엔진에 붙인다. 등록이 끝나면 바로 반환한다(논블로킹).

    - scheduler: 엔진 주소. 기본은 환경 변수 MSDF_SCHEDULER 또는 http://127.0.0.1:8787
    - required=False면 엔진이 없을 때 경고만 내고, 백그라운드에서 계속 연결을 시도한다.
    - token: 엔진을 msdf up --token(또는 MSDF_TOKEN)으로 띄웠다면 같은 값. 기본은 MSDF_TOKEN
    - block=True면 반환하지 않고 Ctrl+C(SIGINT)나 SIGTERM을 받을 때까지 기다린다.
      자기 메인 루프가 없는 서비스(Action만 제공하는 서비스)에 쓴다.
    """
    if _CLIENT:
        if block:
            _wait_forever()
        return
    _require_runtime()
    scheduler = scheduler or os.environ.get("MSDF_SCHEDULER", DEFAULT_SCHEDULER)
    entry = _caller_file()
    project_root = root or os.path.dirname(entry)
    registry = collect(project_root, entry=entry)
    if not registry.services:
        raise RegistrationError(
            f"{entry}에서 import로 닿는 @service가 없습니다.",
            file=entry,
            fix="start()는 @service가 있는 파일(또는 그 파일을 import하는 파일)에서 호출하세요.",
        )
    token = token or os.environ.get("MSDF_TOKEN") or None
    client = Client(registry, scheduler, host=host, port=port, token=token)
    client.serve()
    deadline = None if timeout is None else time.time() + timeout
    warned = False
    while True:
        try:
            ok = client.register_once()
        except RegistrationError:
            client.stop()
            raise
        if ok:
            break
        if not required:
            log.warning(
                "MSDF: 엔진(%s)에 연결하지 못했습니다. 백그라운드에서 다시 시도합니다.", scheduler
            )
            break
        if deadline is not None and time.time() > deadline:
            client.stop()
            raise RegistrationError(
                f"엔진({scheduler})에 연결하지 못했습니다.", fix="msdf up으로 엔진을 먼저 띄우세요."
            )
        if not warned:
            log.warning(
                "MSDF: 엔진(%s)을 기다리는 중... (msdf up을 띄웠는지 확인하세요)", scheduler
            )
            warned = True
        time.sleep(1.0)
    threading.Thread(target=client.heartbeat_loop, daemon=True, name="msdf-heartbeat").start()
    set_backend(client)
    _CLIENT.append(client)
    atexit.register(stop)
    if block:
        _wait_forever()


def _wait_forever() -> None:
    done = threading.Event()
    with contextlib.suppress(ValueError):  # 메인 스레드가 아니면 시그널을 걸 수 없다
        signal.signal(signal.SIGTERM, lambda *_: done.set())
    log.warning("MSDF: 서비스 실행 중 (Ctrl+C로 종료)")
    try:
        while not done.wait(1.0):
            pass
    except KeyboardInterrupt:
        pass
    stop()


def stop() -> None:
    """엔진에서 등록을 해제한다. 프로세스가 끝날 때 자동으로 불린다."""
    while _CLIENT:
        _CLIENT.pop().stop()
    set_backend(None)


def current_client() -> Client | None:
    return _CLIENT[0] if _CLIENT else None

"""Worker: start()가 서비스 프로세스 안에 띄우는 작은 수신 서버.

한 번에 한 단계만 실행한다. /run은 즉시 202를 돌려주고 실제 실행은 백그라운드 스레드에서 한다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException

from ms_dataflow.execute.runner import run_task
from ms_dataflow.models import StepResult, StepTask
from ms_dataflow.registry import Registry
from ms_dataflow.resolvers import ResolverPool

log = logging.getLogger("msdf.worker")


class Worker:
    def __init__(
        self,
        registry: Registry,
        report: Callable[[StepResult], None],
        instance_id: Callable[[], str],
    ) -> None:
        self.registry = registry
        self.report = report
        self.instance_id = instance_id
        self.pool = ResolverPool()
        self.busy: tuple[str, int] | None = None
        self.cancelled: set[tuple[str, int]] = set()
        self._lock = threading.Lock()

    def accept(self, task: StepTask) -> None:
        with self._lock:
            if self.busy is not None:
                raise HTTPException(409, "다른 단계를 실행 중입니다")
            self.busy = (task.run_id, task.step_no)
        threading.Thread(target=self._run, args=(task,), daemon=True, name="msdf-step").start()

    def _run(self, task: StepTask) -> None:
        spec = self.registry.action(task.service, task.action)
        try:
            if spec is None:
                result = StepResult(
                    run_id=task.run_id,
                    step_no=task.step_no,
                    ok=False,
                    error=f"이 프로세스에 Action {task.service}.{task.action}이 없습니다",
                    error_kind="other",
                )
            else:
                result = run_task(task, spec, self.pool, [self.registry.root])
        except Exception as e:  # noqa: BLE001
            log.exception("단계 실행 중 예외")
            result = StepResult(
                run_id=task.run_id, step_no=task.step_no, ok=False, error=str(e), error_kind="other"
            )
        key = (task.run_id, task.step_no)
        with self._lock:
            self.busy = None
            if key in self.cancelled:
                self.cancelled.discard(key)
                return
        # 결과를 확실히 전달하는 것은 Worker의 책임이다
        for attempt in range(30):
            try:
                self.report(result)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("결과 보고 실패(%d): %s", attempt + 1, e)
                time.sleep(min(2.0, 0.1 * 2**attempt))
        log.error("결과를 보고하지 못했습니다: %s:%s", task.run_id, task.step_no)

    def app(self) -> FastAPI:
        app = FastAPI(title="MSDF worker")
        worker = self

        @app.post("/run", status_code=202)
        def run(task: StepTask) -> dict[str, bool]:
            worker.accept(task)
            return {"accepted": True}

        @app.get("/health")
        def health() -> dict[str, Any]:
            return {
                "instance_id": worker.instance_id(),
                "services": sorted(worker.registry.services),
                "busy": list(worker.busy) if worker.busy else None,
            }

        @app.post("/cancel")
        def cancel(body: dict[str, Any]) -> dict[str, bool]:
            key = (str(body.get("run_id")), int(body.get("step_no", 0)))
            with worker._lock:
                if worker.busy == key:
                    worker.cancelled.add(key)
            return {"ok": True}

        return app

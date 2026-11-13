"""LocalRunner: 엔진과 서비스를 프로세스 하나에서 돌린다.

Worker 서버 없이 흐름 전체(캐시, 부분 재계산, 재시도, 배달)를 확인하는 데 쓴다.
테스트와 예제 검증용이며, 운영에서는 ``msdf up`` + ``start()``를 쓴다.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ms_dataflow.decorators import current_context, set_backend
from ms_dataflow.errors import OrderError
from ms_dataflow.execute.engine import Engine, Submitted
from ms_dataflow.execute.runner import run_task
from ms_dataflow.models import Order, Settings, StepResult
from ms_dataflow.project import Project, load_project
from ms_dataflow.resolvers import ResolverPool
from ms_dataflow.store import Store


class LocalRunner:
    def __init__(
        self,
        root: str | Path,
        *,
        config_dir: str | Path | None = None,
        db: str | Path = ":memory:",
        settings: Settings | None = None,
        install: bool = True,
        sleep: bool = True,
    ) -> None:
        self.project: Project = load_project(root, config_dir=config_dir)
        self.store = Store(db)
        self.engine = Engine(
            self.store,
            self.project.registry,
            self.project.dags,
            self.project.resolvers,
            iam=self.project.iam,
            settings=settings,
        )
        self.pool = ResolverPool()
        self.sleep = sleep
        self.last: Submitted | None = None
        if install:
            set_backend(self)

    # order() 백엔드
    def submit(
        self,
        name: str,
        params: dict[str, Any],
        caller_file: str,
        meta: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        subscribe: float | None = None,
    ) -> str:
        requester = self.project.registry.owner_of(caller_file)
        if requester is None:
            raise OrderError(
                f"{caller_file}이 어느 서비스에 속하는지 알 수 없습니다. "
                "order()는 @service에서 import로 닿는 파일에서 호출하세요."
            )
        return self.order(
            name,
            params,
            requester=requester,
            meta=meta,
            idempotency_key=idempotency_key,
            subscribe=subscribe,
        )

    def order(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        *,
        requester: str,
        context: dict[str, str] | None = None,
        meta: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        subscribe: float | None = None,
    ) -> str:
        """요청을 넣고 request_id를 돌려준다. subscribe는 초(0 = 만료 없음)."""
        ctx = context if context is not None else current_context()
        self.last = self.engine.submit(
            Order(
                name=name,
                params=params or {},
                requester=requester,
                context=ctx,
                meta=meta or {},
                idempotency_key=idempotency_key,
                subscribe=subscribe,
            )
        )
        return self.last.run_id

    def invalidate(
        self,
        action: str,
        params: dict[str, Any] | None,
        data_version: str | None,
        caller_file: str,
    ) -> dict[str, Any]:
        service = self.project.registry.owner_of(caller_file)
        if service is None:
            raise OrderError(f"{caller_file}이 어느 서비스에 속하는지 알 수 없습니다.")
        return self.engine.invalidate(service, action, params, data_version)

    def cancel(self, request_id: str) -> dict[str, Any]:
        return self.engine.cancel(request_id)

    def cancel_request(self, request_id: str, caller_file: str) -> dict[str, Any]:
        requester = self.project.registry.owner_of(caller_file)
        if requester is None:
            raise OrderError(f"{caller_file}이 어느 서비스에 속하는지 알 수 없습니다.")
        try:
            return self.engine.cancel(request_id, requester=requester)
        except KeyError:
            raise OrderError(f"요청 {request_id}이 없습니다.") from None

    def delete(self, key: str, cascade: bool, caller_file: str) -> dict[str, Any]:
        requester = self.project.registry.owner_of(caller_file)
        if requester is None:
            raise OrderError(f"{caller_file}이 어느 서비스에 속하는지 알 수 없습니다.")
        return self.engine.delete(requester, current_context(), key, cascade)

    def step_once(self) -> list[StepResult]:
        results = []
        self.engine.pump()  # 구독: 만료 정리, source가 바뀐 구독의 refresh 시작
        for task in self.engine.ready():
            if not self.engine.lease(task.run_id, task.step_no, "local"):
                continue
            self.engine.running(task.run_id, task.step_no)
            spec = self.project.registry.action(task.service, task.action)
            assert spec is not None
            result = run_task(task, spec, self.pool, [str(self.project.root)])
            self.engine.complete(result)
            results.append(result)
        return results

    def run_until_idle(self, max_rounds: int = 10_000) -> None:
        """할 일이 없을 때까지 단계를 실행한다. 재시도 대기는 기다린다."""
        for _ in range(max_rounds):
            if self.step_once():
                continue
            if self.engine.pending() == 0:
                return
            wake = self.engine.next_wakeup()
            if wake is None:
                return  # 남은 단계가 의존성 때문에 막혀 있다
            delay = wake - time.time()
            if delay > 0:
                if not self.sleep:
                    return
                time.sleep(min(delay, 1.0))
        raise RuntimeError("run_until_idle: 끝나지 않습니다")

    def close(self) -> None:
        set_backend(None)
        self.pool.close()
        self.store.close()

    def __enter__(self) -> LocalRunner:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

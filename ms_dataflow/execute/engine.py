"""엔진 코어: order 접수, 계획, 큐, 결과 등록, 재시도, 실패 전파.

동기 코드이며 한 스레드에서만 부른다(Scheduler의 DB 전용 스레드, 또는 LocalRunner).
그래서 SQLite에 쓰는 것은 항상 이 객체 하나다.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from ms_dataflow import ids, ops
from ms_dataflow.config.dag import ancestors, delivery_for
from ms_dataflow.config.resolvers import ResolverConfig
from ms_dataflow.errors import (
    ParamError,
    PermissionDenied,
    ServiceUnavailable,
    UnknownOrder,
)
from ms_dataflow.models import (
    ACTIVE,
    Dag,
    Delivery,
    InputRef,
    Order,
    OutputRef,
    Settings,
    StepResult,
    StepTask,
    split_ref,
)
from ms_dataflow.planner import InFlight, Plan, plan, root_params
from ms_dataflow.registry import Registry
from ms_dataflow.store import Store

_ACTIVE_SQL = "('" + "','".join(ACTIVE) + "')"


class Authorizer(Protocol):
    def check_order(self, order: Order, dag: Dag, delivery: Delivery) -> list[str]:
        """막힌 엣지 목록. 비어 있으면 허용."""
        ...

    def delete_allowed(self, requester: str, context: dict[str, str], target: str) -> bool: ...


@dataclass(frozen=True)
class Submitted:
    run_id: str
    lineage_key: str
    plan: Plan


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Engine:
    def __init__(
        self,
        store: Store,
        registry: Registry,
        dags: dict[str, Dag],
        resolvers: ResolverConfig,
        *,
        iam: Authorizer | None = None,
        settings: Settings | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.registry = registry
        self.dags = dags
        self.resolvers = resolvers
        self.iam = iam
        self.settings = settings or Settings()
        self.clock = clock
        self.available: set[str] | None = None  # None이면 레지스트리의 서비스가 모두 있다고 본다
        self._last_now = 0.0
        self.on_register: list[Callable[[list[str]], object]] = [lambda c: ops.retain(self, c)]

    def now(self) -> float:
        # generation이 겹치지 않도록 단조 증가시킨다
        t = self.clock()
        if t <= self._last_now:
            t = self._last_now + 1e-6
        self._last_now = t
        return t

    # --- PlanLookup ------------------------------------------------------
    def fresh(
        self, step_key: str, outputs: tuple[str, ...], fresh_for: timedelta | None, now: float
    ) -> dict[str, str] | None:
        rows = self.store.query(
            """SELECT a.generation, a.slot, a.id, a.created_at FROM artifact a
               LEFT JOIN artifact_tombstone t ON t.artifact_id = a.id
               WHERE a.step_key = ? AND t.artifact_id IS NULL
               ORDER BY a.generation DESC""",
            (step_key,),
        )
        by_gen: dict[float, dict[str, tuple[str, float]]] = {}
        for r in rows:
            by_gen.setdefault(r["generation"], {})[r["slot"]] = (r["id"], r["created_at"])
        for gen in sorted(by_gen, reverse=True):
            slots = by_gen[gen]
            if not set(outputs) <= set(slots):
                continue
            created = min(slots[s][1] for s in outputs)
            if fresh_for is not None and now - created >= fresh_for.total_seconds():
                return None  # 가장 최근 것이 만료되었으면 새로 만든다
            return {s: slots[s][0] for s in outputs}
        return None

    def inflight(self, step_key: str) -> InFlight | None:
        rows = self.store.query(
            f"""SELECT run_id, step_no, generation, outputs FROM step
                WHERE step_key = ? AND kind = 'produce' AND status IN {_ACTIVE_SQL}""",
            (step_key,),
        )
        if not rows:
            return None
        r = rows[0]
        outs = json.loads(r["outputs"])
        return InFlight(
            f"{r['run_id']}:{r['step_no']}",
            r["generation"],
            {s: v["artifact_id"] for s, v in outs.items()},
        )

    # --- order 접수 --------------------------------------------------------
    def check(self, order: Order) -> tuple[Dag, Delivery]:
        dag = self.dags.get(order.name)
        if dag is None:
            raise UnknownOrder(f"order '{order.name}'에 해당하는 DAG가 없습니다.")
        delivery = delivery_for(dag, order.requester)
        if delivery is None:
            raise UnknownOrder(
                f"DAG '{order.name}'의 deliveries에 요청 서비스 '{order.requester}'가 없습니다."
            )
        expected = root_params(dag, self.registry.actions)
        got = set(order.params)
        if got != expected:
            parts = []
            if expected - got:
                parts.append("빠진 것: " + ", ".join(sorted(expected - got)))
            if got - expected:
                parts.append("남는 것: " + ", ".join(sorted(got - expected)))
            raise ParamError(f"order '{order.name}'의 params가 맞지 않습니다. " + "; ".join(parts))
        rn, _ = split_ref(dag.result)
        services = {dag.nodes[n].service for n in ancestors(dag, rn)} | {order.requester}
        missing = sorted(
            s
            for s in services
            if s not in self.registry.services
            or (self.available is not None and s not in self.available)
        )
        missing_actions = [
            f"{dag.nodes[n].service}.{dag.nodes[n].action}"
            for n in ancestors(dag, rn)
            if self.registry.action(dag.nodes[n].service, dag.nodes[n].action) is None
            and dag.nodes[n].service not in missing
        ]
        if missing or missing_actions:
            raise ServiceUnavailable(
                "경로의 서비스가 떠 있지 않습니다: " + ", ".join(missing + missing_actions),
                missing + missing_actions,
            )
        if self.iam is not None:
            blocked = self.iam.check_order(order, dag, delivery)
            if blocked:
                raise PermissionDenied("IAM 규칙에 막혔습니다: " + ", ".join(blocked), blocked)
        return dag, delivery

    def submit(self, order: Order) -> Submitted:
        dag, delivery = self.check(order)
        run_id = ids.run_id(f"{order.name}:{uuid.uuid4()}")
        with self.store.tx() as db:
            now = self.now()
            db.execute(
                """INSERT INTO run (run_id, order_name, requester, params, context, status,
                   created_at) VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (run_id, order.name, order.requester, _j(order.params), _j(order.context), now),
            )
            p = self._enqueue(run_id, dag, delivery, order, now, first_no=1)
        return Submitted(run_id, p.result_lineage, p)

    def _enqueue(
        self, run_id: str, dag: Dag, delivery: Delivery, order: Order, now: float, first_no: int
    ) -> Plan:
        p = plan(dag, self.registry.actions, dict(order.params), self, now)
        offset = first_no - 1

        def ref(r: str) -> str:
            return f"{run_id}:{int(r[5:]) + offset}" if r.startswith("self:") else r

        db = self.store.conn
        for s in p.steps:
            db.execute(
                """INSERT INTO step (run_id, step_no, kind, node, service, action, step_key,
                   generation, version, inputs, params, outputs, deps, status, max_retries,
                   retry_delay, queued_at)
                   VALUES (?, ?, 'produce', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (
                    run_id,
                    s.no + offset,
                    s.node,
                    s.service,
                    s.action,
                    s.step_key,
                    s.generation,
                    s.version,
                    _j(s.inputs),
                    _j(s.params),
                    _j(
                        {
                            k: {"lineage_key": lk, "artifact_id": a}
                            for k, (lk, a) in s.outputs.items()
                        }
                    ),
                    _j([ref(d) for d in s.deps]),
                    s.retries,
                    s.retry_delay,
                    now,
                ),
            )
        svc, act = split_ref(delivery.on_success)
        spec = self.registry.action(svc, act)
        slot = spec.inputs[0] if spec and spec.inputs else "result"
        deps = [ref(p.result_ref)] if p.result_ref else []
        db.execute(
            """INSERT INTO step (run_id, step_no, kind, service, action, inputs, deps, status,
               max_retries, retry_delay, queued_at)
               VALUES (?, ?, 'deliver', ?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (
                run_id,
                len(p.steps) + 1 + offset,
                svc,
                act,
                _j({slot: p.result_artifact}),
                _j(deps),
                spec.retries if spec else 0,
                spec.retry_delay if spec else 0.0,
                now,
            ),
        )
        db.execute(
            "UPDATE run SET result_lineage = ?, result_artifact = ?, plan = ? WHERE run_id = ?",
            (
                p.result_lineage,
                p.result_artifact,
                _j({"steps": [s.node for s in p.steps], "cached": p.cached, "joined": p.joined}),
                run_id,
            ),
        )
        return p

    # --- 큐 ----------------------------------------------------------------
    def _status_of(self, refs: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in refs:
            run_id, no = r.rsplit(":", 1)
            row = self.store.query(
                "SELECT status FROM step WHERE run_id = ? AND step_no = ?", (run_id, int(no))
            )
            out[r] = row[0]["status"] if row else "missing"
        return out

    def ready(self, now: float | None = None, services: set[str] | None = None) -> list[StepTask]:
        """지금 실행할 수 있는 단계. 의존 단계가 모두 끝났고 재시도 대기가 지난 것."""
        now = self.clock() if now is None else now
        rows = self.store.query(
            "SELECT * FROM step WHERE status = 'queued' AND not_before <= ? "
            "ORDER BY queued_at, run_id, step_no",
            (now,),
        )
        tasks: list[StepTask] = []
        for r in rows:
            if services is not None and r["service"] not in services:
                continue
            deps = json.loads(r["deps"])
            if deps and any(v != "done" for v in self._status_of(deps).values()):
                continue
            tasks.append(self.task(r))
        return tasks

    def task(self, r: Any) -> StepTask:
        inputs: dict[str, InputRef] = {}
        for slot, aid in json.loads(r["inputs"]).items():
            inputs[slot] = InputRef(artifact_id=aid, backend=self._backend_of(aid))
        outputs = {
            slot: OutputRef(
                lineage_key=v["lineage_key"],
                backend=self.resolvers.backend_for(r["service"], r["action"], slot),
            )
            for slot, v in json.loads(r["outputs"]).items()
        }
        return StepTask(
            run_id=r["run_id"],
            step_no=r["step_no"],
            kind=r["kind"],
            service=r["service"],
            action=r["action"],
            generation=r["generation"],
            inputs=inputs,
            params=json.loads(r["params"]),
            outputs=outputs,
            status=r["fail_status"],
            attempt=r["attempts"] + 1,
        )

    def _backend_of(self, artifact_id: str) -> dict[str, Any]:
        for table in ("artifact", "cold.artifact"):
            rows = self.store.query(f"SELECT backend FROM {table} WHERE id = ?", (artifact_id,))
            if rows:
                value: dict[str, Any] = json.loads(rows[0]["backend"])
                return value
        return dict(self.resolvers.default)

    def lease(self, run_id: str, step_no: int, worker: str, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        with self.store.tx() as db:
            cur = db.execute(
                """UPDATE step SET status = 'leased', worker = ?, lease_until = ?
                   WHERE run_id = ? AND step_no = ? AND status = 'queued'""",
                (worker, now + self.settings.lease_ttl, run_id, step_no),
            )
        return cur.rowcount == 1

    def running(self, run_id: str, step_no: int, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self.store.tx() as db:
            db.execute(
                """UPDATE step SET status = 'running', started_at = ?
                   WHERE run_id = ? AND step_no = ? AND status = 'leased'""",
                (now, run_id, step_no),
            )

    def release(self, run_id: str, step_no: int) -> None:
        """보내지 못한 단계를 큐로 되돌린다."""
        with self.store.tx() as db:
            db.execute(
                """UPDATE step SET status = 'queued', worker = NULL, lease_until = NULL
                   WHERE run_id = ? AND step_no = ? AND status IN ('leased', 'running')""",
                (run_id, step_no),
            )

    def heartbeat(self, worker: str, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        with self.store.tx() as db:
            cur = db.execute(
                """UPDATE step SET lease_until = ? WHERE worker = ?
                   AND status IN ('leased', 'running')""",
                (now + self.settings.lease_ttl, worker),
            )
        return cur.rowcount

    def reap(self, now: float | None = None) -> int:
        """lease가 만료된 단계를 queued로 되돌린다. 재시도 횟수는 늘리지 않는다."""
        now = self.clock() if now is None else now
        with self.store.tx() as db:
            cur = db.execute(
                """UPDATE step SET status = 'queued', worker = NULL, lease_until = NULL
                   WHERE status IN ('leased', 'running') AND lease_until < ?""",
                (now,),
            )
        return cur.rowcount

    def release_worker(self, worker: str) -> int:
        """죽은 인스턴스의 단계를 즉시 되돌린다."""
        with self.store.tx() as db:
            cur = db.execute(
                """UPDATE step SET status = 'queued', worker = NULL, lease_until = NULL
                   WHERE worker = ? AND status IN ('leased', 'running')""",
                (worker,),
            )
        return cur.rowcount

    # --- 결과 ---------------------------------------------------------------
    def _row(self, run_id: str, step_no: int) -> Any:
        rows = self.store.query(
            "SELECT * FROM step WHERE run_id = ? AND step_no = ?", (run_id, step_no)
        )
        return rows[0] if rows else None

    def complete(self, result: StepResult, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        row = self._row(result.run_id, result.step_no)
        if row is None or row["status"] in ("done", "failed", "cancelled"):
            return  # 중복 보고는 무시한다
        if result.ok:
            if row["kind"] == "produce":
                problem = self._register(row, result, now)
                if problem:
                    self._fail(row, problem, now)
                return
            with self.store.tx() as db:
                db.execute(
                    """UPDATE step SET status = 'done', done_at = ?, error = NULL
                       WHERE run_id = ? AND step_no = ?""",
                    (now, row["run_id"], row["step_no"]),
                )
                status = "done" if row["kind"] == "deliver" else "failed"
                # 취소한 run은 실패 배달이 끝나도 'cancelled'로 남는다
                db.execute(
                    """UPDATE run
                       SET status = CASE WHEN status = 'cancelled' THEN status ELSE ? END,
                       finished_at = ? WHERE run_id = ?""",
                    (status, now, row["run_id"]),
                )
            return
        if result.error_kind == "lost" and result.lost_artifact:
            self._lost(row, result.lost_artifact, now)
            return
        attempts = row["attempts"] + 1
        if result.error_kind == "action" and attempts <= row["max_retries"]:
            delay = row["retry_delay"] * (2 ** (attempts - 1))
            with self.store.tx() as db:
                db.execute(
                    """UPDATE step SET status = 'queued', worker = NULL, lease_until = NULL,
                       attempts = ?, not_before = ?, error = ?
                       WHERE run_id = ? AND step_no = ?""",
                    (attempts, now + delay, result.error, row["run_id"], row["step_no"]),
                )
            return
        with self.store.tx() as db:
            db.execute(
                "UPDATE step SET attempts = ? WHERE run_id = ? AND step_no = ?",
                (attempts, row["run_id"], row["step_no"]),
            )
        self._fail(row, result.error or "실패", now)

    def _register(self, row: Any, result: StepResult, now: float) -> str | None:
        planned = json.loads(row["outputs"])
        saved = {o.slot: o for o in result.outputs}
        if set(saved) != set(planned):
            return f"출력 슬롯이 맞지 않습니다: {sorted(saved)} != {sorted(planned)}"
        for slot, o in saved.items():
            if o.artifact_id != planned[slot]["artifact_id"]:
                return (
                    f"artifact_id 불일치 ({slot}): planned {planned[slot]['artifact_id']}, "
                    f"saved {o.artifact_id}. Planner와 Resolver가 다른 ID를 냈습니다."
                )
        inputs: dict[str, str] = json.loads(row["inputs"])
        params = json.loads(row["params"])
        created: list[str] = []
        with self.store.tx() as db:
            db.execute(
                "UPDATE step SET status = 'saved', saved_at = ? WHERE run_id = ? AND step_no = ?",
                (now, row["run_id"], row["step_no"]),
            )
            for slot, o in saved.items():
                db.execute(
                    """INSERT OR IGNORE INTO artifact (id, lineage_key, step_key, generation,
                       service, action, slot, version, order_params, backend, location, checksum,
                       nbytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        o.artifact_id,
                        o.lineage_key,
                        row["step_key"],
                        row["generation"],
                        row["service"],
                        row["action"],
                        slot,
                        row["version"],
                        _j(params) if params else None,
                        _j(self.resolvers.backend_for(row["service"], row["action"], slot)),
                        o.location,
                        o.checksum,
                        o.nbytes,
                        now,
                    ),
                )
                for in_slot, parent in inputs.items():
                    db.execute(
                        "INSERT OR IGNORE INTO artifact_edge VALUES (?, ?, ?)",
                        (parent, o.artifact_id, in_slot),
                    )
                created.append(o.artifact_id)
            db.execute(
                """UPDATE step SET status = 'done', done_at = ?, error = NULL
                   WHERE run_id = ? AND step_no = ?""",
                (now, row["run_id"], row["step_no"]),
            )
        for hook in self.on_register:
            hook(created)
        return None

    # --- 실패 전파 -----------------------------------------------------------
    def _dependents(self, ref: str) -> list[Any]:
        """ref에 (간접적으로) 기대는 진행 중 단계들."""
        rows = self.store.query(f"SELECT * FROM step WHERE status IN {_ACTIVE_SQL}")
        by_dep: dict[str, list[Any]] = {}
        for r in rows:
            for d in json.loads(r["deps"]):
                by_dep.setdefault(d, []).append(r)
        out: list[Any] = []
        seen: set[str] = set()
        stack = [ref]
        while stack:
            cur = stack.pop()
            for r in by_dep.get(cur, []):
                key = f"{r['run_id']}:{r['step_no']}"
                if key not in seen:
                    seen.add(key)
                    out.append(r)
                    stack.append(key)
        return out

    def _fail(self, row: Any, error: str, now: float) -> None:
        ref = f"{row['run_id']}:{row['step_no']}"
        dependents = self._dependents(ref) if row["kind"] == "produce" else []
        affected: dict[str, str] = {}
        if row["kind"] == "produce":
            affected[row["run_id"]] = "failed"
        for d in dependents:
            affected.setdefault(d["run_id"], "cancelled")
        with self.store.tx() as db:
            db.execute(
                """UPDATE step SET status = 'failed', error = ?, done_at = ?, worker = NULL
                   WHERE run_id = ? AND step_no = ?""",
                (error, now, row["run_id"], row["step_no"]),
            )
            for d in dependents:
                db.execute(
                    """UPDATE step SET status = 'cancelled', error = ?, done_at = ?, worker = NULL
                       WHERE run_id = ? AND step_no = ?""",
                    (f"상위 단계 실패: {ref}", now, d["run_id"], d["step_no"]),
                )
            if row["kind"] != "produce":
                db.execute(
                    "UPDATE run SET status = 'failed', error = ?, finished_at = ? WHERE run_id = ?",
                    (error, now, row["run_id"]),
                )
            for run_id, status in affected.items():
                self._deliver_fail(db, run_id, status, error, now)

    def _deliver_fail(self, db: Any, run_id: str, status: str, error: str, now: float) -> None:
        run = db.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
        if run is None or run["status"] != "running":
            return
        dag = self.dags.get(run["order_name"])
        delivery = delivery_for(dag, run["requester"]) if dag else None
        db.execute("UPDATE run SET error = ? WHERE run_id = ?", (error, run_id))
        if delivery is None:
            db.execute(
                "UPDATE run SET status = 'failed', finished_at = ? WHERE run_id = ?", (now, run_id)
            )
            return
        svc, act = split_ref(delivery.on_fail)
        spec = self.registry.action(svc, act)
        (next_no,) = db.execute(
            "SELECT coalesce(max(step_no), 0) + 1 FROM step WHERE run_id = ?", (run_id,)
        ).fetchone()
        db.execute(
            """INSERT INTO step (run_id, step_no, kind, service, action, fail_status, status,
               max_retries, retry_delay, queued_at)
               VALUES (?, ?, 'deliver_fail', ?, ?, ?, 'queued', ?, ?, ?)""",
            (
                run_id,
                next_no,
                svc,
                act,
                status,
                spec.retries if spec else 0,
                spec.retry_delay if spec else 0.0,
                now,
            ),
        )

    def _lost(self, row: Any, artifact_id: str, now: float) -> None:
        """입력 데이터 본체가 사라졌다. 캐시 미스로 보고 영향받은 run을 다시 계획한다."""
        ref = f"{row['run_id']}:{row['step_no']}"
        dependents = self._dependents(ref)
        runs = {row["run_id"]} | {d["run_id"] for d in dependents}
        with self.store.tx() as db:
            db.execute(
                """INSERT OR IGNORE INTO artifact_tombstone (artifact_id, deleted_at, reason,
                   body_deleted) VALUES (?, ?, 'lost', 1)""",
                (artifact_id, now),
            )
            for run_id in runs:
                db.execute(
                    f"""UPDATE step SET status = 'cancelled', error = ?, done_at = ?, worker = NULL
                        WHERE run_id = ? AND status IN {_ACTIVE_SQL}""",
                    (f"입력 데이터 유실({artifact_id[:12]})로 다시 계획", now, run_id),
                )
            for run_id in sorted(runs):
                run = db.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
                if run is None or run["status"] != "running":
                    continue
                dag = self.dags.get(run["order_name"])
                delivery = delivery_for(dag, run["requester"]) if dag else None
                if dag is None or delivery is None or run["replans"] >= self.settings.max_replans:
                    self._deliver_fail(db, run_id, "failed", "입력 데이터 유실", now)
                    continue
                order = Order(
                    name=run["order_name"],
                    params=json.loads(run["params"]),
                    requester=run["requester"],
                    context=json.loads(run["context"]),
                )
                (next_no,) = db.execute(
                    "SELECT coalesce(max(step_no), 0) + 1 FROM step WHERE run_id = ?", (run_id,)
                ).fetchone()
                db.execute("UPDATE run SET replans = replans + 1 WHERE run_id = ?", (run_id,))
                self._enqueue(run_id, dag, delivery, order, self.now(), first_no=next_no)

    # --- 취소 --------------------------------------------------------------
    def cancel(
        self, run_id: str, reason: str = "사용자가 취소", now: float | None = None
    ) -> dict[str, Any]:
        """진행 중인 run을 멈춘다. 요청 서비스에는 on_fail로 status="cancelled"가 배달된다.

        다른 run이 함께 기다리는(합류한) 단계는 멈추지 않는다. 이미 서비스에서 실행 중인 단계는
        끝까지 돌지만 결과는 버린다.
        """
        now = self.clock() if now is None else now
        rows = self.store.query("SELECT * FROM run WHERE run_id = ?", (run_id,))
        if not rows:
            raise KeyError(run_id)
        if rows[0]["status"] != "running":
            return {"ok": False, "status": rows[0]["status"], "cancelled": 0}
        mine = self.store.query(
            f"SELECT * FROM step WHERE run_id = ? AND status IN {_ACTIVE_SQL}", (run_id,)
        )
        shared: set[int] = set()
        for r in mine:
            ref = f"{run_id}:{r['step_no']}"
            if any(d["run_id"] != run_id for d in self._dependents(ref)):
                shared.add(r["step_no"])
        stop = [r for r in mine if r["step_no"] not in shared]
        with self.store.tx() as db:
            for r in stop:
                db.execute(
                    """UPDATE step SET status = 'cancelled', error = ?, done_at = ?, worker = NULL,
                       lease_until = NULL WHERE run_id = ? AND step_no = ?""",
                    (reason, now, run_id, r["step_no"]),
                )
            self._deliver_fail(db, run_id, "cancelled", reason, now)
            db.execute(
                """UPDATE run SET status = 'cancelled', error = ?,
                   finished_at = CASE WHEN EXISTS (SELECT 1 FROM step WHERE run_id = ?
                     AND kind = 'deliver_fail' AND status = 'queued') THEN NULL ELSE ? END
                   WHERE run_id = ?""",
                (reason, run_id, now, run_id),
            )
        return {"ok": True, "status": "cancelled", "cancelled": len(stop), "kept": len(shared)}

    # --- 삭제 --------------------------------------------------------------
    def delete(
        self, requester: str, context: dict[str, str], lineage_key: str, cascade: bool = False
    ) -> dict[str, Any]:
        return ops.delete(self, requester, context, lineage_key, cascade)

    def purge(self) -> int:
        return ops.purge(self)

    # --- 조회 --------------------------------------------------------------
    def run(self, run_id: str) -> dict[str, Any] | None:
        rows = self.store.query("SELECT * FROM run WHERE run_id = ?", (run_id,))
        return dict(rows[0]) if rows else None

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.store.query(
                "SELECT * FROM step WHERE run_id = ? ORDER BY step_no", (run_id,)
            )
        ]

    def pending(self) -> int:
        rows = self.store.query(f"SELECT count(*) AS n FROM step WHERE status IN {_ACTIVE_SQL}")
        return int(rows[0]["n"])

    def next_wakeup(self, now: float | None = None) -> float | None:
        """재시도 대기 중인 단계가 깨어날 가장 이른 시각."""
        now = self.clock() if now is None else now
        rows = self.store.query(
            "SELECT min(not_before) AS t FROM step WHERE status = 'queued' AND not_before > ?",
            (now,),
        )
        t = rows[0]["t"]
        return float(t) if t is not None else None

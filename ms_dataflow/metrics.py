"""UI용 집계: 실시간 맵의 수치, 로그 조회. 엔진 DB 스레드에서 읽기만 한다."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from typing import Any

from ms_dataflow.config.dag import incoming
from ms_dataflow.models import Dag, split_ref
from ms_dataflow.store import Store

_RUNNING = ("leased", "running", "saved")


def _since(window: float, now: float) -> float:
    return now - window if window > 0 else 0.0


def _ms(a: float | None, b: float | None) -> float | None:
    return round((b - a) * 1000, 1) if a and b else None


def overview(
    store: Store, dags: dict[str, Dag], window: float, now: float | None = None
) -> dict[str, Any]:
    """맵 한 장에 필요한 모든 수치."""
    now = time.time() if now is None else now
    since = _since(window, now)

    # Action별 단계 통계
    actions: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "done": 0,
            "failed": 0,
            "cancelled": 0,
            "running": 0,
            "queued": 0,
            "cached": 0,
            "retries": 0,
            "avg_ms": None,
            "last_error": None,
            "last_at": None,
        }
    )
    rows = store.query(
        """SELECT service, action, status, count(*) AS n, sum(attempts) AS retries,
                  avg(CASE WHEN status = 'done' THEN done_at - started_at END) AS avg_s,
                  max(coalesce(done_at, started_at, queued_at)) AS last_at
           FROM step WHERE queued_at >= ?
           GROUP BY service, action, status""",
        (since,),
    )
    for r in rows:
        a = actions[f"{r['service']}.{r['action']}"]
        key = "running" if r["status"] in _RUNNING else r["status"]
        a[key] = a.get(key, 0) + r["n"]
        a["retries"] += r["retries"] or 0
        if r["avg_s"] is not None:
            a["avg_ms"] = round(r["avg_s"] * 1000, 1)
        a["last_at"] = max(a["last_at"] or 0, r["last_at"] or 0) or None
    for r in store.query(
        """SELECT service, action, error FROM step WHERE status = 'failed' AND queued_at >= ?
           ORDER BY done_at DESC""",
        (since,),
    ):
        a = actions[f"{r['service']}.{r['action']}"]
        if a["last_error"] is None and r["error"]:
            a["last_error"] = r["error"].strip().splitlines()[-1][:300]

    # 실행(run) 통계와 캐시
    runs = store.query("SELECT * FROM run WHERE created_at >= ?", (since,))
    dag_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "runs": 0,
            "done": 0,
            "failed": 0,
            "running": 0,
            "cache_hits": 0,
            "avg_ms": None,
            "last_run": None,
            "_dur": [],
        }
    )
    cached_by_node: dict[tuple[str, str], int] = defaultdict(int)
    executed = cached_total = full_hits = 0
    for r in runs:
        d = dag_stats[r["order_name"]]
        d["runs"] += 1
        d[r["status"]] = d.get(r["status"], 0) + 1
        d["last_run"] = max(d["last_run"] or 0, r["created_at"])
        if r["finished_at"] and r["status"] == "done":
            d["_dur"].append(r["finished_at"] - r["created_at"])
        plan = json.loads(r["plan"]) if r["plan"] else {}
        cached = plan.get("cached", [])
        executed += len(plan.get("steps", []))
        cached_total += len(cached)
        if plan and not plan.get("steps") and not plan.get("joined"):
            full_hits += 1
            d["cache_hits"] += 1
        dag = dags.get(r["order_name"])
        for node in cached:
            cached_by_node[(r["order_name"], node)] += 1
            if dag and node in dag.nodes:
                n = dag.nodes[node]
                actions[f"{n.service}.{n.action}"]["cached"] += 1
    for d in dag_stats.values():
        durs = d.pop("_dur")
        if durs:
            d["avg_ms"] = round(sum(durs) / len(durs) * 1000, 1)

    # 엣지별 데이터 이동 수
    node_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in store.query(
        """SELECT r.order_name, s.node, s.kind, s.status, count(*) AS n
           FROM step s JOIN run r ON r.run_id = s.run_id
           WHERE s.queued_at >= ? GROUP BY 1, 2, 3, 4""",
        (since,),
    ):
        key = r["node"] if r["kind"] == "produce" else f"@{r['kind']}"
        node_counts[(r["order_name"], key, r["status"])] += r["n"]
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def edge(src: str, dst: str, kind: str) -> dict[str, Any]:
        k = (src, dst, kind)
        if k not in edges:
            edges[k] = {
                "from": src,
                "to": dst,
                "kind": kind,
                "orders": [],
                "count": 0,
                "failed": 0,
                "running": 0,
            }
        return edges[k]

    for order, dag in dags.items():
        inc = incoming(dag)
        for child, slots in inc.items():
            for slot, (parent, pslot) in slots.items():
                p, c = dag.nodes[parent], dag.nodes[child]
                e = edge(f"{p.service}.{p.action}", f"{c.service}.{c.action}", "data")
                if order not in e["orders"]:
                    e["orders"].append(order)
                e.setdefault("slots", []).append(f"{pslot}→{slot}")
                e["count"] += node_counts[(order, child, "done")] + cached_by_node[(order, child)]
                e["failed"] += node_counts[(order, child, "failed")]
                e["running"] += sum(node_counts[(order, child, s)] for s in _RUNNING)
        rn, _ = split_ref(dag.result)
        res = dag.nodes.get(rn)
        if res is None:
            continue
        for dl in dag.deliveries:
            e = edge(f"{res.service}.{res.action}", dl.on_success, "delivery")
            if order not in e["orders"]:
                e["orders"].append(order)
            e["count"] += node_counts[(order, "@deliver", "done")]
            e["running"] += sum(node_counts[(order, "@deliver", s)] for s in _RUNNING)
            f = edge(f"{res.service}.{res.action}", dl.on_fail, "failure")
            if order not in f["orders"]:
                f["orders"].append(order)
            f["count"] += node_counts[(order, "@deliver_fail", "done")]

    # 시간대별 처리량 (30칸)
    span = window if window > 0 else 3600.0
    size = span / 30
    timeline = [{"t": now - span + i * size, "done": 0, "failed": 0} for i in range(30)]
    for r in store.query(
        """SELECT done_at, status FROM step WHERE kind = 'produce'
           AND status IN ('done', 'failed') AND done_at >= ?""",
        (now - span,),
    ):
        i = min(29, max(0, int((r["done_at"] - (now - span)) / size)))
        timeline[i][r["status"]] += 1

    totals = {
        "runs": len(runs),
        "runs_done": sum(1 for r in runs if r["status"] == "done"),
        "runs_failed": sum(1 for r in runs if r["status"] == "failed"),
        "runs_running": sum(1 for r in runs if r["status"] == "running"),
        "steps_done": sum(a["done"] for a in actions.values()),
        "steps_failed": sum(a["failed"] for a in actions.values()),
        "steps_running": sum(a["running"] for a in actions.values()),
        "steps_queued": sum(a["queued"] for a in actions.values()),
        "retries": sum(a["retries"] for a in actions.values()),
        "cache_full_hits": full_hits,
        "cache_hit_rate": round(cached_total / (cached_total + executed), 3)
        if cached_total + executed
        else None,
    }
    return {
        "now": now,
        "window": window,
        "totals": totals,
        "actions": dict(actions),
        "edges": list(edges.values()),
        "dags": dict(dag_stats),
        "timeline": timeline,
    }


def steps_log(
    store: Store,
    *,
    service: str | None = None,
    order: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
    q: str | None = None,
    limit: int = 100,
    before: float | None = None,
) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    args: list[Any] = []
    if service:
        where.append("s.service = ?")
        args.append(service)
    if order:
        where.append("r.order_name = ?")
        args.append(order)
    if status:
        if status == "running":
            where.append("s.status IN ('leased', 'running', 'saved')")
        else:
            where.append("s.status = ?")
            args.append(status)
    if run_id:
        where.append("s.run_id = ?")
        args.append(run_id)
    if q:
        where.append("(s.run_id LIKE ? OR s.action LIKE ? OR s.node LIKE ? OR s.error LIKE ?)")
        args += [f"%{q}%"] * 4
    if before:
        where.append("s.queued_at < ?")
        args.append(before)
    rows = store.query(
        f"""SELECT s.*, r.order_name, r.requester FROM step s JOIN run r ON r.run_id = s.run_id
            WHERE {" AND ".join(where)} ORDER BY s.queued_at DESC, s.step_no DESC LIMIT ?""",
        (*args, min(limit, 1000)),
    )
    out = []
    for r in rows:
        d = dict(r)
        for k in ("inputs", "outputs", "params", "deps"):
            d[k] = json.loads(d[k])
        d["duration_ms"] = _ms(d["started_at"], d["done_at"])
        d["wait_ms"] = _ms(d["queued_at"], d["started_at"])
        out.append(d)
    return out


def runs_log(
    store: Store,
    *,
    order: str | None = None,
    requester: str | None = None,
    status: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
    before: float | None = None,
) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    args: list[Any] = []
    for col, val in (
        ("order_name", order),
        ("requester", requester),
        ("status", status),
        ("run_id", run_id),
    ):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if before:
        where.append("created_at < ?")
        args.append(before)
    rows = store.query(
        f"SELECT * FROM run WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?",
        (*args, min(limit, 1000)),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["params"] = json.loads(d["params"])
        d["context"] = json.loads(d["context"])
        d["plan"] = json.loads(d["plan"]) if d["plan"] else None
        d["duration_ms"] = _ms(d["created_at"], d["finished_at"])
        out.append(d)
    return out


class LogBuffer(logging.Handler):
    """엔진 로그(msdf.*)를 최근 N개만 메모리에 둔다. UI의 엔진 로그 탭이 읽는다."""

    def __init__(self, size: int = 3000) -> None:
        super().__init__(level=logging.INFO)
        self.items: deque[dict[str, Any]] = deque(maxlen=size)
        self.seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.seq += 1
        self.items.append(
            {
                "seq": self.seq,
                "t": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
        )

    def emit_message(self, message: str, level: str = "INFO") -> None:
        logging.getLogger("msdf.ui").log(getattr(logging, level), message)

    def query(
        self, *, after: int = 0, q: str | None = None, level: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        items = [i for i in list(self.items) if i["seq"] > after]
        if level:
            items = [i for i in items if i["level"] == level]
        if q:
            items = [i for i in items if q.lower() in i["message"].lower()]
        return items[-limit:]

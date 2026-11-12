"""삭제 요청과 보관 정책(hot/cold). 엔진의 DB 스레드에서 돈다.

삭제: IAM 검사 → 삭제 표시(tombstone) 먼저 → Resolver로 본체 삭제(실패하면 표시를 둔 채 재시도).
보관: hot에는 같은 요청의 최신 N개 generation과, 같은 자리에서 version만 바뀐 복제본의 최신 M개만
둔다. 나머지 메타데이터는 cold로 옮긴다(하위 Artifact도 함께). 본체와 계보 연결은 옮기지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ms_dataflow.errors import OrderError, PermissionDenied
from ms_dataflow.resolvers import ResolverPool

if TYPE_CHECKING:
    from ms_dataflow.execute.engine import Engine

log = logging.getLogger("msdf.ops")


# --- 삭제 ----------------------------------------------------------------------
def _children(engine: Engine, ids: list[str]) -> list[str]:
    out: list[str] = []
    seen = set(ids)
    stack = list(ids)
    while stack:
        cur = stack.pop()
        for r in engine.store.query(
            "SELECT child_id FROM artifact_edge WHERE parent_id = ?", (cur,)
        ):
            c = r["child_id"]
            if c not in seen:
                seen.add(c)
                out.append(c)
                stack.append(c)
    return out


def _rows(engine: Engine, ids: list[str]) -> list[Any]:
    rows: list[Any] = []
    for table in ("artifact", "cold.artifact"):
        for aid in ids:
            rows += engine.store.query(f"SELECT * FROM {table} WHERE id = ?", (aid,))
    return rows


def delete(
    engine: Engine,
    requester: str,
    context: dict[str, str],
    lineage_key: str,
    cascade: bool = False,
) -> dict[str, Any]:
    """order()가 돌려준 키(요청의 정체)로 만든 데이터를 지운다."""
    targets = [
        r["id"]
        for table in ("artifact", "cold.artifact")
        for r in engine.store.query(
            f"""SELECT a.id FROM {table} a LEFT JOIN artifact_tombstone t ON t.artifact_id = a.id
                WHERE a.lineage_key = ? AND t.artifact_id IS NULL""",
            (lineage_key,),
        )
    ]
    if not targets:
        raise OrderError(f"지울 데이터가 없습니다 (키 {lineage_key[:12]}…)")
    roots = list(targets)
    if cascade:
        targets += _children(engine, roots)
    rows = _rows(engine, targets)
    if engine.iam is not None:
        denied = sorted(
            {
                f"delete: {requester} → {r['service']}.{r['action']}.{r['slot']}"
                for r in rows
                if not engine.iam.delete_allowed(
                    requester, context, f"{r['service']}.{r['action']}.{r['slot']}"
                )
            }
        )
        if denied:
            raise PermissionDenied("IAM 규칙에 막혔습니다: " + ", ".join(denied), denied)
    now = engine.now()
    root_of = {aid: (roots[0] if cascade and aid not in roots else None) for aid in targets}
    with engine.store.tx() as db:
        for r in rows:
            db.execute(
                """INSERT OR IGNORE INTO artifact_tombstone (artifact_id, deleted_at, reason,
                   account, service, cascade_root) VALUES (?, ?, 'requested', ?, ?, ?)""",
                (r["id"], now, context.get("account"), requester, root_of.get(r["id"])),
            )
    pending = purge(engine)
    log.info("삭제: %d개 (본체 삭제 대기 %d)", len(rows), pending)
    return {"deleted": [r["id"] for r in rows], "pending": pending}


_POOL = ResolverPool()


def purge(engine: Engine) -> int:
    """삭제 표시만 되고 본체가 남은 것을 지운다. 남은 개수를 돌려준다."""
    rows = engine.store.query(
        "SELECT artifact_id FROM artifact_tombstone WHERE body_deleted = 0 AND reason = 'requested'"
    )
    left = 0
    for r in rows:
        aid = r["artifact_id"]
        try:
            backend = engine._backend_of(aid)
            _POOL.get(backend).delete(aid)
        except Exception as e:  # noqa: BLE001
            log.warning("본체 삭제 실패, 나중에 다시 시도: %s (%s)", aid, e)
            left += 1
            continue
        with engine.store.tx() as db:
            db.execute(
                "UPDATE artifact_tombstone SET body_deleted = 1 WHERE artifact_id = ?", (aid,)
            )
    return left


# --- 보관 ----------------------------------------------------------------------
def _move_to_cold(engine: Engine, ids: list[str]) -> int:
    if not ids:
        return 0
    moving = list(dict.fromkeys(ids + _children(engine, ids)))
    hot = [
        aid for aid in moving if engine.store.query("SELECT 1 FROM artifact WHERE id = ?", (aid,))
    ]
    with engine.store.tx() as db:
        for aid in hot:
            db.execute("INSERT INTO cold.artifact SELECT * FROM main.artifact WHERE id = ?", (aid,))
            db.execute("DELETE FROM main.artifact WHERE id = ?", (aid,))
    return len(hot)


def retain(engine: Engine, created: list[str]) -> int:
    """방금 등록한 Artifact를 기준으로 N, M을 넘는 것을 cold로 옮긴다."""
    n_keep = engine.settings.keep_generations
    m_keep = engine.settings.keep_versions
    old: list[str] = []
    for aid in created:
        row = engine.store.query("SELECT * FROM artifact WHERE id = ?", (aid,))
        if not row:
            continue
        a = row[0]
        # N: 같은 요청(lineage_key)의 generation
        same = engine.store.query(
            "SELECT id FROM artifact WHERE lineage_key = ? ORDER BY generation DESC",
            (a["lineage_key"],),
        )
        old += [r["id"] for r in same[n_keep:]]
        # M: 같은 자리(같은 부모, 같은 service.action.slot)의 version 복제본
        parents = sorted(
            r["parent_id"]
            for r in engine.store.query(
                "SELECT parent_id FROM artifact_edge WHERE child_id = ?", (aid,)
            )
        )
        siblings = engine.store.query(
            """SELECT id, version, created_at, order_params FROM artifact
               WHERE service = ? AND action = ? AND slot = ? AND version != ?""",
            (a["service"], a["action"], a["slot"], a["version"]),
        )
        same_place = []
        for s in siblings:
            sp = sorted(
                r["parent_id"]
                for r in engine.store.query(
                    "SELECT parent_id FROM artifact_edge WHERE child_id = ?", (s["id"],)
                )
            )
            if sp == parents and (parents or s["order_params"] == a["order_params"]):
                same_place.append(s)
        latest_by_version: dict[str, Any] = {}
        for s in same_place:
            cur = latest_by_version.get(s["version"])
            if cur is None or s["created_at"] > cur["created_at"]:
                latest_by_version[s["version"]] = s
        versions = sorted(latest_by_version.values(), key=lambda s: -s["created_at"])
        # 방금 만든 것이 최신 하나를 차지하므로 다른 version은 M-1개까지 남긴다
        drop_versions = {s["version"] for s in versions[max(0, m_keep - 1) :]}
        old += [s["id"] for s in same_place if s["version"] in drop_versions]
    moved = _move_to_cold(engine, sorted(set(old)))
    if moved:
        log.info("보관 정책: %d개를 cold로 옮김", moved)
    return moved


def lineage(engine: Engine, artifact_id: str) -> dict[str, Any]:
    """계보 추적(hot과 cold 모두). UI와 디버깅용."""
    rows = _rows(engine, [artifact_id])
    if not rows:
        return {}
    a = dict(rows[0])
    a["tier"] = (
        "hot"
        if engine.store.query("SELECT 1 FROM artifact WHERE id = ?", (artifact_id,))
        else "cold"
    )
    tomb = engine.store.query(
        "SELECT * FROM artifact_tombstone WHERE artifact_id = ?", (artifact_id,)
    )
    a["deleted"] = dict(tomb[0]) if tomb else None
    a["parents"] = [
        {"slot": r["slot"], **lineage(engine, r["parent_id"])}
        for r in engine.store.query(
            "SELECT parent_id, slot FROM artifact_edge WHERE child_id = ?", (artifact_id,)
        )
    ]
    if a.get("order_params"):
        a["order_params"] = json.loads(a["order_params"])
    return a

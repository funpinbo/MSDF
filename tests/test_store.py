from __future__ import annotations

import sqlite3

import pytest

from ms_dataflow.errors import ConfigError
from ms_dataflow.store import SCHEMA_VERSION, Store, _schema_sql


def _old_sql(version: int) -> str:
    """현재 schema.sql에서 그 버전 이후에 추가된 부분을 뺀다."""
    keep = []
    sql = _schema_sql()
    if version < 7:
        a = sql.index("-- ready(): 실행할 수 있는")
        b = sql.index("CREATE INDEX IF NOT EXISTS idx_step_dep ON step_dep(dep);")
        sql = sql[:a] + sql[b + len("CREATE INDEX IF NOT EXISTS idx_step_dep ON step_dep(dep);") :]
    if version < 5:
        sql = sql[: sql.index("-- subscribe:")]
    if version < 4:
        sql = sql[: sql.index("-- 데이터 주인 서비스가 invalidate()")]
    for line in sql.splitlines(keepends=True):
        if version < 5 and line.lstrip().startswith(("subscription_id ", "refresh_no ")):
            continue
        if version < 7 and line.lstrip().startswith("waiting "):
            continue
        if version < 6 and line.lstrip().startswith("idle_since "):
            continue
        if version < 6 and line.lstrip().startswith("last_checksum "):
            line = line.replace("TEXT,", "TEXT ", 1)
        if version < 3 and (
            line.lstrip().startswith(("meta ", "idempotency_key "))
            or "idx_run_idempotency" in line
            or "WHERE idempotency_key" in line
        ):
            continue
        if version < 2 and line.lstrip().startswith("plan "):
            continue
        keep.append(line)
    return "".join(keep)


def _make(path, version: int):
    sql = _old_sql(version)
    assert ("idempotency_key" in sql) == (version >= 3)
    conn = sqlite3.connect(path)
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO run(run_id, order_name, requester, params, context, status, created_at)"
        " VALUES ('r1', 'o', 'app', '{}', '{}', 'done', 1.0)"
    )
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


def _make_v1(path):
    _make(path, 1)


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
def test_migrates_old_versions(tmp_path, version):
    db = tmp_path / "msdf.db"
    _make(db, version)
    store = Store(db)
    row = store.query("SELECT run_id, plan, meta, idempotency_key FROM run")[0]
    assert row["run_id"] == "r1" and row["meta"] is None
    assert store.query("PRAGMA user_version")[0][0] == SCHEMA_VERSION
    store.close()
    assert (tmp_path / f"msdf.db.v{version}.bak").exists()


def test_migrates_v1_and_keeps_rows(tmp_path):
    db = tmp_path / "msdf.db"
    _make_v1(db)
    store = Store(db)
    (v,) = store.query("PRAGMA user_version")[0]
    assert v == SCHEMA_VERSION
    row = store.query("SELECT run_id, plan FROM run")[0]
    assert row["run_id"] == "r1" and row["plan"] is None
    store.close()
    assert (tmp_path / "msdf.db.v1.bak").exists()
    Store(db).close()  # 두 번째 열기는 변환 없이


def test_newer_db_is_refused(tmp_path):
    db = tmp_path / "msdf.db"
    Store(db).close()
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(ConfigError) as e:
        Store(db)
    assert "더 새 버전" in e.value.reason


def test_v7_migration_computes_waiting_for_queued_steps(tmp_path):
    """업그레이드 직후에도 진행 중이던 단계가 정확히 그 deps를 기다린다."""
    db = tmp_path / "msdf.db"
    _make(db, 6)
    conn = sqlite3.connect(db)
    rows = [
        # run r1: 1(done) → 2(queued, deps 1) → 3(queued, deps 2) ; 4(queued, deps 1, 2)
        ("r1", 1, "done", "[]"),
        ("r1", 2, "queued", '["r1:1"]'),
        ("r1", 3, "queued", '["r1:2"]'),
        ("r1", 4, "queued", '["r1:1", "r1:2"]'),
        ("r1", 5, "queued", '["gone:9"]'),  # 없는 단계를 기다림 → 실행되면 안 된다
    ]
    for run_id, no, status, deps in rows:
        conn.execute(
            "INSERT INTO step (run_id, step_no, kind, service, action, deps, status) "
            "VALUES (?, ?, 'produce', 's', 'a', ?, ?)",
            (run_id, no, deps, status),
        )
    conn.commit()
    conn.close()
    store = Store(db)
    got = {r["step_no"]: r["waiting"] for r in store.query("SELECT step_no, waiting FROM step")}
    assert got == {1: 0, 2: 0, 3: 1, 4: 1, 5: 1}
    deps = store.query("SELECT count(*) FROM step_dep")[0][0]
    assert deps == 5
    store.close()

from __future__ import annotations

import sqlite3

import pytest

from ms_dataflow.errors import ConfigError
from ms_dataflow.store import SCHEMA_VERSION, Store, _schema_sql


def _old_sql(version: int) -> str:
    """현재 schema.sql에서 그 버전 이후에 추가된 부분을 뺀다."""
    keep = []
    for line in _schema_sql().splitlines(keepends=True):
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


@pytest.mark.parametrize("version", [1, 2])
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

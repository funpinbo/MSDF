from __future__ import annotations

import sqlite3

import pytest

from ms_dataflow.errors import ConfigError
from ms_dataflow.store import SCHEMA_VERSION, Store, _schema_sql


def _make_v1(path):
    sql = _schema_sql().replace(
        '  plan            TEXT,               -- {"steps": [노드], "cached": [노드], "joined": [노드]} (JSON)\n',
        "",
    )
    assert "plan  " not in sql
    conn = sqlite3.connect(path)
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO run(run_id, order_name, requester, params, context, status, created_at)"
        " VALUES ('r1', 'o', 'app', '{}', '{}', 'done', 1.0)"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


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

"""SQLite Resolver (내장). 사용자 데이터용 SQLite 파일이며, 엔진의 메타데이터 DB와는 별개다."""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ms_dataflow import ids
from ms_dataflow.errors import ArtifactMissing, ResolverError
from ms_dataflow.resolvers.base import Saved, checksum, decode, encode

_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqliteResolver:
    def __init__(
        self,
        path: str = "./store.db",
        table: str = "msdf_artifact",
        allow_pickle: bool = False,
        **_: Any,
    ) -> None:
        if not _TABLE.match(table):
            raise ResolverError(f"테이블 이름이 올바르지 않습니다: {table!r}")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.table = table
        self.allow_pickle = allow_pickle
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                artifact_id TEXT PRIMARY KEY,
                save_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                data BLOB NOT NULL,
                checksum TEXT NOT NULL
            )"""
        )
        self.conn.commit()

    def exists(self, lineage_key: str, generation: float) -> str | None:
        with self._lock:
            row = self.conn.execute(
                f"SELECT artifact_id FROM {self.table} WHERE save_key = ?",
                (ids.save_key(lineage_key, generation),),
            ).fetchone()
        return row[0] if row else None

    def save(self, lineage_key: str, generation: float, data: Any, parents: list[str]) -> Saved:
        aid = ids.artifact_id(parents, lineage_key, generation)
        with self._lock:
            row = self.conn.execute(
                f"SELECT checksum, length(data) FROM {self.table} WHERE artifact_id = ?", (aid,)
            ).fetchone()
        if row:
            return Saved(aid, self.locate(aid), row[0], row[1])
        kind, raw = encode(data, self.allow_pickle)
        digest = checksum(raw)
        with self._lock:
            self.conn.execute(
                f"INSERT OR IGNORE INTO {self.table} VALUES (?, ?, ?, ?, ?)",
                (aid, ids.save_key(lineage_key, generation), kind, raw, digest),
            )
            self.conn.commit()
        return Saved(aid, self.locate(aid), digest, len(raw))

    def load(self, artifact_id: str) -> Any:
        with self._lock:
            row = self.conn.execute(
                f"SELECT kind, data FROM {self.table} WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise ArtifactMissing(f"{artifact_id}의 데이터가 {self.path}에 없습니다")
        return decode(row[0], row[1])

    def locate(self, artifact_id: str) -> str:
        return f"sqlite://{self.path}#{self.table}/{artifact_id}"

    def delete(self, artifact_id: str) -> None:
        with self._lock:
            self.conn.execute(f"DELETE FROM {self.table} WHERE artifact_id = ?", (artifact_id,))
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

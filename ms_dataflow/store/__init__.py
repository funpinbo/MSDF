"""엔진의 SQLite 메타데이터 저장소. 쓰는 쪽은 엔진(Scheduler) 하나뿐이다."""

from __future__ import annotations

import logging
import sqlite3
import threading
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from ms_dataflow.errors import ConfigError

log = logging.getLogger("msdf.store")

SCHEMA_VERSION = 5

# 버전 n의 DB를 n+1로 올리는 SQL. 표와 인덱스 생성은 schema.sql이 (IF NOT EXISTS로) 맡으므로
# 여기에는 기존 표를 바꾸는 문장만 둔다.
MIGRATIONS: dict[int, str] = {
    1: "ALTER TABLE run ADD COLUMN plan TEXT;",
    2: "ALTER TABLE run ADD COLUMN meta TEXT; ALTER TABLE run ADD COLUMN idempotency_key TEXT;",
    3: "",  # source_version 표만 추가 (schema.sql이 만든다)
    4: "ALTER TABLE run ADD COLUMN subscription_id TEXT; "
    "ALTER TABLE run ADD COLUMN refresh_no INTEGER NOT NULL DEFAULT 0;",
}
_MIN_SQLITE = (3, 35, 0)
_COLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS cold.artifact AS SELECT * FROM main.artifact WHERE 0;
"""


def _schema_sql() -> str:
    return resources.files("ms_dataflow.store").joinpath("schema.sql").read_text("utf-8")


class Store:
    """SQLite 연결 하나. 같은 Store는 한 스레드에서만 쓴다."""

    def __init__(self, path: str | Path = ":memory:", cold_path: str | Path | None = None) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        if sqlite3.sqlite_version_info < _MIN_SQLITE:  # pragma: no cover
            warnings.warn(
                f"SQLite {sqlite3.sqlite_version}은 오래되었습니다. 3.35 이상을 권장합니다.",
                stacklevel=2,
            )
        self.conn = sqlite3.connect(
            self.path, timeout=5.0, isolation_level=None, check_same_thread=False
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA busy_timeout = 5000;
            PRAGMA foreign_keys = ON;
            """
        )
        self._lock = threading.RLock()
        self._check_version()
        self.conn.executescript(_schema_sql())
        if cold_path is None:
            cold_path = (
                ":memory:" if self.path == ":memory:" else str(Path(self.path).with_name("cold.db"))
            )
        self.conn.execute("ATTACH DATABASE ? AS cold", (str(cold_path),))
        self.conn.executescript(_COLD_SCHEMA)

    def _check_version(self) -> None:
        (current,) = self.conn.execute("PRAGMA user_version").fetchone()
        has_tables = self.conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        if current == 0 and not has_tables:
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        if current == SCHEMA_VERSION:
            return
        if current > SCHEMA_VERSION or any(
            v not in MIGRATIONS for v in range(current, SCHEMA_VERSION)
        ):
            raise ConfigError(
                f"이 DB는 스키마 v{current}로 만들어졌고, 이 MSDF는 v{SCHEMA_VERSION}을 씁니다.\n"
                "  자동으로 변환할 수 없습니다"
                + (" (더 새 버전의 MSDF가 만든 DB입니다)." if current > SCHEMA_VERSION else "."),
                file=self.path,
                fix=f"MSDF 버전을 맞추거나, {self.path}를 지우고 다시 시작하세요. (캐시와 실행 "
                "이력만 사라지며, Resolver가 저장한 실제 데이터는 영향을 받지 않습니다.)",
            )
        self._migrate(current)

    def _migrate(self, current: int) -> None:
        """v{current} → v{SCHEMA_VERSION}. 파일 DB면 먼저 백업을 남긴다."""
        if self.path != ":memory:":
            backup = f"{self.path}.v{current}.bak"
            dst = sqlite3.connect(backup)
            try:
                self.conn.backup(dst)
            finally:
                dst.close()
            log.warning(
                "MSDF: DB 스키마를 v%d → v%d로 변환합니다 (백업: %s)",
                current,
                SCHEMA_VERSION,
                backup,
            )
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for v in range(current, SCHEMA_VERSION):
                for stmt in filter(None, (x.strip() for x in MIGRATIONS[v].split(";"))):
                    self.conn.execute(stmt)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """쓰기 트랜잭션. BEGIN IMMEDIATE로 시작해 짧게 끝낸다."""
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def query(self, sql: str, args: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

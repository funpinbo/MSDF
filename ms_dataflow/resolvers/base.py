"""Resolver 인터페이스와 데이터 변환(코덱)."""

from __future__ import annotations

import hashlib
import io
import json
import pickle
from dataclasses import dataclass
from functools import singledispatch
from typing import Any, Protocol, runtime_checkable

from ms_dataflow.errors import UnsupportedType


@dataclass(frozen=True)
class Saved:
    artifact_id: str
    location: str
    checksum: str
    nbytes: int


@runtime_checkable
class Resolver(Protocol):
    """저장 백엔드. DB 종류를 아는 유일한 층이다."""

    def save(self, lineage_key: str, generation: float, data: Any, parents: list[str]) -> Saved:
        """(lineage_key, generation)이 이미 저장돼 있으면 쓰지 않고 같은 ID를 돌려준다."""
        ...

    def load(self, artifact_id: str) -> Any:
        """없으면 ArtifactMissing."""
        ...

    def locate(self, artifact_id: str) -> str: ...

    def delete(self, artifact_id: str) -> None: ...

    def exists(self, lineage_key: str, generation: float) -> str | None: ...

    def close(self) -> None: ...


# --- 코덱 --------------------------------------------------------------------
@singledispatch
def encode(data: Any, allow_pickle: bool = False) -> tuple[str, bytes]:
    """데이터 → (형식, 바이트). DataFrame=parquet, dict/list/스칼라=json, bytes=그대로."""
    if _is_dataframe(data):
        buf = io.BytesIO()
        data.to_parquet(buf)
        return "parquet", buf.getvalue()
    if allow_pickle:
        return "pickle", pickle.dumps(data)
    raise UnsupportedType(
        f"{type(data).__name__}은 저장할 수 없습니다. "
        "DataFrame, dict, list, str, 숫자, bytes를 쓰거나 백엔드에서 allow_pickle을 켜세요."
    )


@encode.register(bytes)
@encode.register(bytearray)
def _(data: bytes, allow_pickle: bool = False) -> tuple[str, bytes]:
    return "bytes", bytes(data)


@encode.register(dict)
@encode.register(list)
@encode.register(tuple)
@encode.register(str)
@encode.register(int)
@encode.register(float)
@encode.register(bool)
@encode.register(type(None))
def _(data: Any, allow_pickle: bool = False) -> tuple[str, bytes]:
    try:
        return "json", json.dumps(data, ensure_ascii=False).encode()
    except TypeError as e:
        if allow_pickle:
            return "pickle", pickle.dumps(data)
        raise UnsupportedType(f"JSON으로 바꿀 수 없는 값이 있습니다: {e}") from None


def decode(kind: str, raw: bytes) -> Any:
    if kind == "json":
        return json.loads(raw)
    if kind == "bytes":
        return raw
    if kind == "parquet":
        import pandas as pd

        return pd.read_parquet(io.BytesIO(raw))
    if kind == "pickle":
        return pickle.loads(raw)  # noqa: S301 - 사용자가 명시적으로 켠 경우만
    raise UnsupportedType(f"알 수 없는 저장 형식: {kind}")


def _is_dataframe(data: Any) -> bool:
    t = type(data)
    return t.__name__ == "DataFrame" and t.__module__.startswith("pandas")


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

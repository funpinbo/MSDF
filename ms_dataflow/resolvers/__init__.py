"""Resolver 백엔드 찾기와 프로세스 안의 Resolver 풀."""

from __future__ import annotations

import threading
from importlib.metadata import entry_points
from typing import Any

from ms_dataflow.errors import ConfigError
from ms_dataflow.ids import canonical_json
from ms_dataflow.resolvers.base import Resolver, Saved

__all__ = ["Resolver", "Saved", "backend_class", "ResolverPool"]


def _builtins() -> dict[str, Any]:
    from ms_dataflow.resolvers.file import FileResolver
    from ms_dataflow.resolvers.sqlite import SqliteResolver

    return {"file": FileResolver, "sqlite": SqliteResolver}


def backend_class(name: str) -> Any:
    """entry point 'msdf.resolvers'에서 백엔드를 찾는다. 쓰는 것만 import한다."""
    for ep in entry_points(group="msdf.resolvers"):
        if ep.name == name:
            return ep.load()
    builtin = _builtins()
    if name in builtin:  # 패키지를 설치하지 않고 소스에서 돌릴 때
        return builtin[name]
    raise ConfigError(
        f"Resolver 백엔드 '{name}'을 찾지 못했습니다.",
        fix="내장 백엔드는 file, sqlite입니다. 다른 백엔드는 패키지를 설치하세요.",
    )


class ResolverPool:
    """백엔드 설정마다 Resolver 하나. Worker는 한 번에 한 단계만 돌므로 풀이 필요 없다."""

    def __init__(self) -> None:
        self._items: dict[str, Resolver] = {}
        self._lock = threading.Lock()

    def get(self, config: dict[str, Any]) -> Resolver:
        key = canonical_json(config)
        with self._lock:
            r = self._items.get(key)
            if r is None:
                opts = dict(config)
                cls = backend_class(str(opts.pop("backend", "file")))
                r = cls(**opts)
                self._items[key] = r
            return r

    def close(self) -> None:
        with self._lock:
            for r in self._items.values():
                r.close()
            self._items.clear()

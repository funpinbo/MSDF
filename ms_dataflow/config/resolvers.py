"""resolvers.yaml: service.action.slot → 저장 백엔드 매핑. 엔진만 들고 있다."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ms_dataflow.config import read_yaml
from ms_dataflow.errors import ConfigError

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PATH_KEYS = {"path"}


def _expand(value: Any, src: str) -> Any:
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in os.environ:
                raise ConfigError(
                    f"환경 변수 {name}가 설정되어 있지 않습니다.",
                    file=src,
                    fix=f"엔진을 띄우기 전에 {name}를 설정하세요.",
                )
            return os.environ[name]

        return _ENV.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v, src) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, src) for v in value]
    return value


@dataclass
class ResolverConfig:
    mapping: dict[str, dict[str, Any]] = field(default_factory=dict)
    default: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None, base: Path) -> ResolverConfig:
        default = {"backend": "file", "path": str((base / ".msdf" / "store").resolve())}
        if path is None or not path.exists():
            return cls({}, default)
        raw = read_yaml(path)
        if not isinstance(raw, dict):
            raise ConfigError("resolvers.yaml은 매핑이어야 합니다.", file=str(path))
        mapping: dict[str, dict[str, Any]] = {}
        for key, cfg in raw.items():
            if not isinstance(cfg, dict) or "backend" not in cfg:
                raise ConfigError(
                    f"'{key}': {{backend: ..., ...}} 형식이어야 합니다.",
                    file=str(path),
                    fix="예: search.fetch.out: {backend: file, path: ./store}",
                )
            cfg = _expand(dict(cfg), str(path))
            for k in _PATH_KEYS:
                if k in cfg and cfg[k] != ":memory:":
                    cfg[k] = str((base / str(cfg[k])).resolve())
            if key == "default":
                default = cfg
            elif len(str(key).split(".")) != 3:
                raise ConfigError(
                    f"키 '{key}'는 서비스.액션.슬롯 형식이어야 합니다.", file=str(path)
                )
            else:
                mapping[str(key)] = cfg
        from ms_dataflow.resolvers import backend_class

        for cfg in [default, *mapping.values()]:
            backend_class(str(cfg["backend"]))  # 없는 백엔드는 로딩 때 막는다
        return cls(mapping, default)

    def backend_for(self, service: str, action: str, slot: str) -> dict[str, Any]:
        return dict(self.mapping.get(f"{service}.{action}.{slot}", self.default))

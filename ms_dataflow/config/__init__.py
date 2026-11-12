"""설정 파일(DAG, IAM, resolvers) 로딩."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ms_dataflow.errors import ConfigError


def read_yaml(path: Path) -> Any:
    try:
        text = path.read_text("utf-8")
    except OSError as e:
        raise ConfigError(f"파일을 읽지 못했습니다: {e}", file=str(path)) from None
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 문법 오류: {e}", file=str(path)) from None


def format_validation(e: ValidationError) -> str:
    lines = []
    for item in e.errors():
        loc = ".".join(str(x) for x in item["loc"]) or "(최상위)"
        msg = item["msg"]
        if item["type"] == "extra_forbidden":
            msg = "모르는 키입니다"
            if item["loc"] and item["loc"][-1] == "version":
                msg = "DAG는 version을 덮어쓸 수 없습니다"
        elif item["type"] == "missing":
            msg = "필수 항목이 빠졌습니다"
        lines.append(f"{loc}: {msg}")
    return "\n  ".join(lines)

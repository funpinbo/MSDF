"""IAM 편집기의 저장소: 화면 형식 ↔ iam.yaml, 검증, 엔진에 바로 반영.

iam.yaml이 원본이다. 화면에서 저장하면 같은 형식의 파일을 쓰고, 엔진의 규칙집을 그 자리에서 바꾼다.
이미 접수된 run은 접수할 때 검사를 마쳤으므로 영향을 받지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ms_dataflow.config import format_validation
from ms_dataflow.config.iam import Iam, IamFile, _validate
from ms_dataflow.errors import ConfigError
from ms_dataflow.models import Order
from ms_dataflow.project import Project


def iam_path(project: Project) -> Path:
    return (project.config_dir or project.root) / "iam.yaml"


def to_json(spec: IamFile | None) -> dict[str, Any]:
    """화면이 쓰는 형식. 조건은 conditions 아래로 모은다."""
    if spec is None:
        return {"layers": [], "rules": []}
    layers = [
        {
            "name": name,
            "kind": layer.kind,
            "levels": list(layer.levels),
            "members": list(layer.members),
        }
        for name, layer in spec.layers.items()
    ]
    rules = []
    for r in spec.rules:
        rules.append(
            {
                "type": r.type,
                "from": r.from_,
                "to": r.to,
                "target": r.target,
                "conditions": {k: v for k, v in r.conditions().items()},
            }
        )
    return {"layers": layers, "rules": rules}


def _raw(data: dict[str, Any]) -> dict[str, Any]:
    """화면 형식 → iam.yaml 형식 (dict)."""
    layers: dict[str, Any] = {}
    for item in data.get("layers") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        layer: dict[str, Any] = {"kind": item.get("kind") or "flat"}
        if item.get("levels"):
            layer["levels"] = [str(x) for x in item["levels"]]
        if item.get("members"):
            layer["members"] = [str(x) for x in item["members"]]
        layers[name] = layer
    rules: list[dict[str, Any]] = []
    for item in data.get("rules") or []:
        rule: dict[str, Any] = {"type": item.get("type")}
        for key in ("from", "to", "target"):
            if item.get(key):
                rule[key] = item[key]
        for k, v in (item.get("conditions") or {}).items():
            if str(k).strip() and v not in (None, "", []):
                rule[str(k).strip()] = v
        rules.append(rule)
    out: dict[str, Any] = {}
    if layers:
        out["layers"] = layers
    out["rules"] = rules
    return out


def _flow(value: Any) -> str:
    return str(
        yaml.safe_dump(
            value, default_flow_style=True, allow_unicode=True, width=10_000, sort_keys=False
        )
    ).strip()


def to_yaml(raw: dict[str, Any]) -> str:
    """손으로 쓴 파일과 같은 모양: 계층은 블록, 규칙은 한 줄씩."""
    lines: list[str] = []
    if raw.get("layers"):
        lines.append("layers:")
        for name, layer in raw["layers"].items():
            lines.append(f"  {name}: {_flow(layer)}")
        lines.append("")
    rules = raw.get("rules") or []
    if not rules:
        lines.append("rules: []")
    else:
        lines.append("rules:")
        for r in rules:
            lines.append(f"  - {_flow(r)}")
    return "\n".join(lines) + "\n"


def check(
    project: Project, data: dict[str, Any]
) -> tuple[IamFile | None, dict[str, Any], list[str]]:
    """(spec, raw, 오류). spec이 None이거나 오류가 있으면 저장하지 않는다."""
    raw = _raw(data)
    try:
        spec = IamFile.model_validate(raw)
    except ValidationError as e:
        return None, raw, format_validation(e).split("\n  ")
    errs = _validate(spec, str(iam_path(project)), project.registry)
    return spec, raw, [e.reason + (f" ({e.fix})" if e.fix else "") for e in errs]


def save(project: Project, spec: IamFile, raw: dict[str, Any], engine: Any = None) -> str:
    path = iam_path(project)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(to_yaml(raw), "utf-8")
    os.replace(tmp, path)
    iam = Iam(spec, str(path))
    project.iam = iam
    if engine is not None:
        engine.iam = iam
    project.warnings = [w for w in project.warnings if not w.startswith("iam.yaml이 없어")]
    return str(path)


def try_order(
    project: Project, order: str, requester: str, context: dict[str, str]
) -> dict[str, Any]:
    """이 서비스가 이 order를 하면 통과하는지 시험한다 (실행하지 않음)."""
    from ms_dataflow.config.dag import delivery_for

    dag = project.dags.get(order)
    if dag is None:
        raise ConfigError(f"DAG '{order}'가 없습니다.")
    delivery = delivery_for(dag, requester)
    if delivery is None:
        return {
            "ok": False,
            "blocked": [f"DAG '{order}'의 deliveries에 요청 서비스 '{requester}'가 없습니다."],
        }
    if project.iam is None:
        return {"ok": True, "blocked": [], "note": "iam.yaml이 없어 모두 허용합니다."}
    o = Order(name=order, params={}, requester=requester, context=context)
    blocked = project.iam.check_order(o, dag, delivery)
    return {"ok": not blocked, "blocked": blocked}

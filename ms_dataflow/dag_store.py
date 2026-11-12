"""DAG 편집기의 저장소: 검증, YAML로 쓰기, 엔진에 바로 반영.

DAG는 파일(dags/<order>.yaml)이 원본이다. 편집기에서 저장하면 같은 형식의 파일을 쓰고,
엔진의 DAG 목록을 그 자리에서 바꾼다. 진행 중인 실행은 이미 만든 계획대로 끝난다.
"""

from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ms_dataflow.config import format_validation
from ms_dataflow.config.dag import validate_dag
from ms_dataflow.errors import ConfigError
from ms_dataflow.models import Dag
from ms_dataflow.project import Project

_ORDER = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


def format_duration(td: timedelta) -> str:
    s = td.total_seconds()
    for unit, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if s >= size and s % size == 0:
            return f"{int(s // size)}{unit}"
    return f"{int(s * 1000)}ms" if s < 1 else f"{s}s"


def _flow(d: dict[str, Any]) -> str:
    return str(yaml.safe_dump(d, default_flow_style=True, allow_unicode=True, width=10_000)).strip()


def to_yaml(dag: Dag) -> str:
    """사람이 읽기 좋은 모양으로 쓴다 (손으로 쓴 파일과 같은 모양)."""
    lines = [f"order: {dag.order}", "", "nodes:"]
    width = max((len(n) for n in dag.nodes), default=0)
    for name, node in dag.nodes.items():
        d: dict[str, Any] = {"service": node.service, "action": node.action}
        if node.fresh_for is not None:
            d["fresh_for"] = format_duration(node.fresh_for)
        if node.retries is not None:
            d["retries"] = node.retries
        if node.retry_delay is not None:
            d["retry_delay"] = node.retry_delay
        lines.append(f"  {(name + ':').ljust(width + 1)} {_flow(d)}")
    lines += ["", "edges:"]
    if not dag.edges:
        lines[-1] = "edges: []"
    for e in dag.edges:
        lines.append(f"  - {{from: {e.from_}, to: {e.to}}}")
    lines += ["", f"result: {dag.result}", "", "deliveries:"]
    for dl in dag.deliveries:
        lines += [
            f"  - requester: {dl.requester}",
            f"    on_success: {dl.on_success}",
            f"    on_fail:    {dl.on_fail}",
        ]
    layout = {k: v for k, v in dag.layout.items() if k in dag.nodes}
    if layout:
        lines += ["", "# 편집기의 노드 위치", "layout:"]
        for name, (x, y) in layout.items():
            lines.append(f"  {name}: [{round(x)}, {round(y)}]")
    return "\n".join(lines) + "\n"


def check(
    project: Project, data: dict[str, Any], original: str | None = None
) -> tuple[Dag | None, list[str], list[str]]:
    """편집기가 보낸 DAG를 검증한다. (dag, 오류, 경고)"""
    try:
        dag = Dag.model_validate(data)
    except ValidationError as e:
        return None, format_validation(e).split("\n  "), []
    errors: list[str] = []
    if not _ORDER.match(dag.order):
        errors.append(f"order 이름 '{dag.order}'은 영문, 숫자, _, -로 지으세요.")
    other = project.dags.get(dag.order)
    if other is not None and dag.order != original:
        errors.append(f"order 이름 '{dag.order}'은 이미 다른 DAG({other.source})가 쓰고 있습니다.")
    errs, warns = validate_dag(dag, project.registry, strict_services=project.strict_services)
    errors += [e.reason + (f" ({e.fix})" if e.fix else "") for e in errs]
    warns = [w.removeprefix(f"{dag.source}: ") for w in warns]
    return dag, errors, warns


def _dag_dir(project: Project) -> Path:
    base = project.config_dir or project.root
    return base / "dags"


def save(project: Project, dag: Dag, original: str | None = None) -> str:
    """파일을 쓰고 엔진의 DAG 목록을 바꾼다. 쓴 파일 경로를 돌려준다."""
    prev = project.dags.get(original or dag.order)
    if prev is not None and prev.source and (original in (None, dag.order)):
        path = Path(prev.source)
    else:
        path = _dag_dir(project) / f"{dag.order}.yaml"
    if path.exists() and (prev is None or Path(prev.source or "") != path):
        raise ConfigError(f"{path} 파일이 이미 있습니다.", file=str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(to_yaml(dag), "utf-8")
    os.replace(tmp, path)
    if original and original != dag.order:
        old = project.dags.pop(original, None)
        if old is not None and old.source and Path(old.source) != path:
            Path(old.source).unlink(missing_ok=True)
    project.dags[dag.order] = dag.model_copy(update={"source": str(path)})
    return str(path)


def remove(project: Project, order: str) -> None:
    dag = project.dags.pop(order, None)
    if dag is None:
        raise ConfigError(f"DAG '{order}'가 없습니다.")
    if dag.source:
        Path(dag.source).unlink(missing_ok=True)

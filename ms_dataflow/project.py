"""프로젝트 로딩: 코드 분석 + DAG + IAM + resolvers를 한 번에 읽고 검증한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ms_dataflow.config.dag import load_dags, validate_dag
from ms_dataflow.config.iam import Iam, load_iam
from ms_dataflow.config.resolvers import ResolverConfig
from ms_dataflow.errors import LoadError, raise_collected
from ms_dataflow.models import Dag
from ms_dataflow.registry import Registry, collect


@dataclass
class Project:
    root: Path
    registry: Registry
    dags: dict[str, Dag]
    resolvers: ResolverConfig
    iam: Iam | None
    warnings: list[str] = field(default_factory=list)
    config_dir: Path | None = None
    strict_services: bool = True


def load_project(
    root: str | Path,
    *,
    config_dir: str | Path | None = None,
    strict_services: bool = True,
) -> Project:
    """오류는 모아서 한 번에 던진다."""
    rootp = Path(root).resolve()
    cfg = Path(config_dir).resolve() if config_dir else rootp
    errors: list[LoadError] = []
    try:
        registry = collect(rootp)
    except LoadError as e:
        errors += getattr(e, "errors", [e])
        registry = Registry(root=str(rootp))
    dags, dag_errors = load_dags(cfg / "dags")
    errors += dag_errors
    warnings = list(registry.warnings)
    for dag in dags.values():
        errs, warns = validate_dag(dag, registry, strict_services=strict_services)
        errors += errs
        warnings += warns
    iam: Iam | None = None
    try:
        iam = load_iam(cfg / "iam.yaml", registry)
    except LoadError as e:
        errors += getattr(e, "errors", [e])
    if iam is None:
        warnings.append("iam.yaml이 없어 권한 검사를 하지 않습니다 (모든 요청 허용).")
    resolvers = ResolverConfig()
    try:
        resolvers = ResolverConfig.load(cfg / "resolvers.yaml", cfg)
    except LoadError as e:
        errors.append(e)
    raise_collected(errors)
    return Project(rootp, registry, dags, resolvers, iam, warnings, cfg, strict_services)

"""IAM: 전역 규칙집. DAG나 artifact 이름은 모른다.

- 계층(layers)은 사용자가 정의한다. ``service`` 계층 값은 엔진이 자동으로 채운다(사칭 불가).
- 기본은 거부다. 규칙에 맞는 것만 통과한다.
- order 시점에 DAG 전체 경로(캐시로 건너뛸 단계 포함)와 on_success 배달 엣지를 검사한다.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from ms_dataflow.config import format_validation, read_yaml
from ms_dataflow.config.dag import ancestors, incoming
from ms_dataflow.errors import ConfigError, raise_collected
from ms_dataflow.models import ActionPattern, Dag, Delivery, Frozen, Order, split_ref

_RESERVED = {"type", "from", "to", "target"}
_CMP = re.compile(r"^\s*(>=|<=|==|>|<)?\s*([A-Za-z0-9_\-]+)\s*$")


class Layer(Frozen):
    kind: Literal["ordered", "flat"]
    levels: tuple[str, ...] = ()
    members: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Layer:
        if self.kind == "ordered" and not self.levels:
            raise ValueError("ordered 계층에는 levels가 필요합니다")
        return self


Condition = str | list[str]


class Rule(Frozen):
    model_config = ConfigDict(frozen=True, extra="allow", populate_by_name=True)
    type: Literal["order", "flow", "delete"]
    from_: ActionPattern | None = Field(default=None, alias="from")
    to: ActionPattern | None = None
    target: str | None = None

    def conditions(self) -> dict[str, Condition]:
        extra = self.model_extra or {}
        return {k: v for k, v in extra.items() if k not in _RESERVED}


class IamFile(Frozen):
    layers: dict[str, Layer] = Field(default_factory=dict)
    rules: tuple[Rule, ...] = ()


class Iam:
    def __init__(self, spec: IamFile, source: str | None = None) -> None:
        self.spec = spec
        self.source = source
        self.layers = dict(spec.layers)
        if "service" not in self.layers:
            self.layers["service"] = Layer(kind="flat")

    # --- 조건 평가 --------------------------------------------------------
    def _match(self, layer: str, cond: Condition, value: str | None) -> bool:
        conds = cond if isinstance(cond, list) else [cond]
        for c in conds:
            c = str(c)
            if c in ("any", "*"):
                return True
            if value is None:
                continue
            spec = self.layers.get(layer)
            if spec is not None and spec.kind == "ordered":
                m = _CMP.match(c)
                if m is None or value not in spec.levels:
                    continue
                op, name = m.group(1) or "==", m.group(2)
                a, b = spec.levels.index(value), spec.levels.index(name)
                if {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b, "==": a == b}[op]:
                    return True
            elif fnmatch.fnmatchcase(value, c):
                return True
        return False

    def _rule_ok(self, rule: Rule, values: dict[str, str]) -> bool:
        return all(self._match(k, c, values.get(k)) for k, c in rule.conditions().items())

    @staticmethod
    def _values(requester: str, context: dict[str, str]) -> dict[str, str]:
        return {**context, "service": requester}

    # --- 공개 검사 --------------------------------------------------------
    def check_order(self, order: Order, dag: Dag, delivery: Delivery) -> list[str]:
        """막힌 것의 목록. 비어 있으면 허용."""
        values = self._values(order.requester, order.context)
        blocked: list[str] = []
        if not any(r.type == "order" and self._rule_ok(r, values) for r in self.spec.rules):
            blocked.append(f"order: {order.requester} → {order.name}")
        rn, _ = split_ref(dag.result)
        nodes = set(ancestors(dag, rn))
        inc = incoming(dag)
        edges: list[tuple[str, str]] = []
        for child in nodes:
            for parent, _slot in inc.get(child, {}).values():
                p, c = dag.nodes[parent], dag.nodes[child]
                edges.append((f"{p.service}.{p.action}", f"{c.service}.{c.action}"))
        r = dag.nodes[rn]
        edges.append((f"{r.service}.{r.action}", delivery.on_success))
        for src, dst in sorted(set(edges)):
            if not self.flow_allowed(src, dst, values):
                blocked.append(f"flow: {src} → {dst}")
        return blocked

    def flow_allowed(self, src: str, dst: str, values: dict[str, str]) -> bool:
        for rule in self.spec.rules:
            if rule.type != "flow" or rule.from_ is None or rule.to is None:
                continue
            if (
                fnmatch.fnmatchcase(src, rule.from_)
                and fnmatch.fnmatchcase(dst, rule.to)
                and self._rule_ok(rule, values)
            ):
                return True
        return False

    def delete_allowed(self, requester: str, context: dict[str, str], target: str) -> bool:
        """target = 지울 Artifact를 만든 service.action.slot"""
        values = self._values(requester, context)
        for rule in self.spec.rules:
            if rule.type != "delete" or rule.target is None:
                continue
            if fnmatch.fnmatchcase(target, rule.target) and self._rule_ok(rule, values):
                return True
        return False

    def required_context(self) -> list[str]:
        """규칙이 실제로 조건을 거는 계층 중 서비스가 @context로 줘야 하는 것."""
        used: set[str] = set()
        for rule in self.spec.rules:
            for k, c in rule.conditions().items():
                if k != "service" and c not in ("any", "*"):
                    used.add(k)
        return sorted(used)

    def missing_context_keys(self, keys: tuple[str, ...] | None) -> list[str]:
        if keys is None:
            return []  # @context가 없으면 서비스 계층만으로 검사한다
        return [k for k in self.required_context() if k not in keys]


def _validate(spec: IamFile, src: str, registry: Any) -> list[ConfigError]:
    errors: list[ConfigError] = []
    layers = dict(spec.layers)
    layers.setdefault("service", Layer(kind="flat"))
    services = set(registry.services) if registry is not None else set()
    flat_members = layers["service"].members
    for i, rule in enumerate(spec.rules, 1):
        where = f"rules[{i}] ({rule.type})"
        conds = rule.conditions()
        for k, c in conds.items():
            if k not in layers:
                errors.append(
                    ConfigError(
                        f"{where}: 정의되지 않은 계층 '{k}'를 씁니다.",
                        file=src,
                        fix=f"layers에 {k}를 정의하거나 조건을 지우세요.",
                    )
                )
                continue
            layer = layers[k]
            for item in c if isinstance(c, list) else [c]:
                item = str(item)
                if item in ("any", "*"):
                    continue
                if layer.kind == "ordered":
                    m = _CMP.match(item)
                    if m is None or m.group(2) not in layer.levels:
                        errors.append(
                            ConfigError(
                                f"{where}: {k} 조건 '{item}'이 올바르지 않습니다.",
                                file=src,
                                fix=f"'>=레벨' 형식으로, 레벨은 {', '.join(layer.levels)} 중 하나.",
                            )
                        )
                elif layer.members and not any(
                    fnmatch.fnmatchcase(mem, item) for mem in layer.members
                ):
                    errors.append(
                        ConfigError(
                            f"{where}: {k} '{item}'이 members에 없습니다.",
                            file=src,
                        )
                    )
        if rule.type == "flow":
            if rule.from_ is None or rule.to is None:
                errors.append(
                    ConfigError(f"{where}: flow 규칙에는 from과 to가 필요합니다.", file=src)
                )
            for layer_name in layers:
                if layer_name == "service" or layer_name in conds:
                    continue
                errors.append(
                    ConfigError(
                        f"{where} {rule.from_} → {rule.to}: '{layer_name}' 조건이 없습니다.",
                        file=src,
                        fix=f"모든 값을 허용하려면 {layer_name}: any 를 명시하세요.",
                    )
                )
        if rule.type == "delete" and rule.target is None:
            errors.append(
                ConfigError(
                    f"{where}: delete 규칙에는 target(service.action.slot 패턴)이 필요합니다.",
                    file=src,
                )
            )
        for pattern in (rule.from_, rule.to):
            if pattern and services:
                svc = pattern.split(".")[0]
                if "*" not in svc and svc not in services and svc not in flat_members:
                    errors.append(
                        ConfigError(f"{where}: 서비스 '{svc}'를 찾지 못했습니다.", file=src)
                    )
    return errors


def load_iam(path: Path, registry: Any = None) -> Iam | None:
    if not path.exists():
        return None
    raw = read_yaml(path)
    try:
        spec = IamFile.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(
            format_validation(e), file=str(path), fix="IAM 형식을 확인하세요."
        ) from None
    raise_collected(_validate(spec, str(path), registry))
    return Iam(spec, str(path))

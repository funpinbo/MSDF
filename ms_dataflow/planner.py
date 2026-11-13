"""Planner: DAG의 result에서 거슬러 올라가며 실행할 단계만 고른다.

순수 함수다. DB에 쓰지 않고, 캐시와 진행 중 단계는 주입한 lookup으로 읽기만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from ms_dataflow import ids
from ms_dataflow.config.dag import ancestors, incoming
from ms_dataflow.models import ActionSpec, Dag, split_ref


@dataclass(frozen=True)
class InFlight:
    """같은 step_key로 이미 진행 중인 생산 단계."""

    ref: str  # "run_id:step_no"
    generation: float
    outputs: dict[str, str]  # 슬롯 → planned artifact_id


class PlanLookup(Protocol):
    def fresh(
        self, step_key: str, outputs: tuple[str, ...], fresh_for: timedelta | None, now: float
    ) -> dict[str, str] | None:
        """만료되지 않은 캐시가 있으면 슬롯 → artifact_id."""
        ...

    def inflight(self, step_key: str) -> InFlight | None: ...

    # 선택: invalidate()로 알린 source 데이터 버전. 없으면 None (step_key가 0.2와 같다)
    # def source_version(self, service: str, action: str, params: dict[str, Any]) -> str | None


def _data_version(lookup: Any, service: str, action: str, params: dict[str, Any]) -> str | None:
    fn = getattr(lookup, "source_version", None)
    return fn(service, action, params) if fn is not None else None


@dataclass
class PlannedStep:
    no: int
    node: str
    service: str
    action: str
    version: str
    step_key: str
    generation: float
    inputs: dict[str, str]  # 슬롯 → artifact_id (planned 또는 실제)
    params: dict[str, Any]
    outputs: dict[str, tuple[str, str]]  # 슬롯 → (lineage_key, planned artifact_id)
    deps: list[str]  # "self:<no>" 또는 "run_id:step_no"
    retries: int
    retry_delay: float


@dataclass
class Plan:
    result_lineage: str
    result_artifact: str
    result_ref: str | None  # 결과를 만드는 단계 (캐시 히트면 None)
    steps: list[PlannedStep] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)  # 캐시로 건너뛴 노드
    joined: list[str] = field(default_factory=list)  # 진행 중 단계에 합류한 노드
    # 결과가 기대는 (service, action, params scope).
    # invalidate()가 어느 구독에 닿는지 판단할 때 쓴다
    sources: list[tuple[str, str, str]] = field(default_factory=list)


def plan(
    dag: Dag,
    actions: dict[tuple[str, str], ActionSpec],
    params: dict[str, Any],
    lookup: PlanLookup,
    now: float,
) -> Plan:
    inc = incoming(dag)
    rn, rs = split_ref(dag.result)
    produced: dict[tuple[str, str], str] = {}  # (노드, 슬롯) → artifact_id
    refs: dict[str, str | None] = {}  # 노드 → 그 노드를 만드는 단계 ref
    steps: list[PlannedStep] = []
    cached: list[str] = []
    joined: list[str] = []
    local: dict[str, InFlight] = {}  # 같은 plan 안에서 같은 단계가 두 번 나오면 하나로
    keys: dict[str, str] = {}  # 노드 → step_key
    sources: list[tuple[str, str, str]] = []

    for name in ancestors(dag, rn):  # 부모가 먼저
        node = dag.nodes[name]
        spec = actions[(node.service, node.action)]
        inputs = {slot: produced[parent] for slot, parent in inc.get(name, {}).items()}
        node_params = {p: params[p] for p in spec.params}
        dv = _data_version(lookup, spec.service, spec.name, node_params)
        key = ids.step_key(spec.service, spec.name, spec.version, inputs, node_params or None, dv)
        keys[name] = key
        sources.append((spec.service, spec.name, ids.params_scope(node_params)))
        fresh_for = node.fresh_for if node.fresh_for is not None else spec.fresh_for

        hit = lookup.fresh(key, spec.outputs, fresh_for, now)
        if hit is not None:
            for slot in spec.outputs:
                produced[(name, slot)] = hit[slot]
            refs[name] = None
            cached.append(name)
            continue

        running = local.get(key) or lookup.inflight(key)
        if running is not None:
            for slot in spec.outputs:
                produced[(name, slot)] = running.outputs[slot]
            refs[name] = running.ref
            joined.append(name)
            continue

        parents = list(inputs.values())
        outputs = {
            slot: (ids.lineage_key(key, slot), ids.planned_id(parents, key, slot, now))
            for slot in spec.outputs
        }
        deps = sorted(
            {r for parent, _ in inc.get(name, {}).values() if (r := refs.get(parent)) is not None}
        )
        no = len(steps) + 1
        steps.append(
            PlannedStep(
                no=no,
                node=name,
                service=spec.service,
                action=spec.name,
                version=spec.version,
                step_key=key,
                generation=now,
                inputs=inputs,
                params=node_params,
                outputs=outputs,
                deps=deps,
                retries=node.retries if node.retries is not None else spec.retries,
                retry_delay=node.retry_delay if node.retry_delay is not None else spec.retry_delay,
            )
        )
        for slot, (_, aid) in outputs.items():
            produced[(name, slot)] = aid
        refs[name] = f"self:{no}"
        local[key] = InFlight(f"self:{no}", now, {s: a for s, (_, a) in outputs.items()})

    return Plan(
        result_lineage=ids.lineage_key(keys[rn], rs),
        result_artifact=produced[(rn, rs)],
        result_ref=refs[rn],
        steps=steps,
        cached=cached,
        joined=joined,
        sources=sources,
    )


def root_params(dag: Dag, actions: dict[tuple[str, str], ActionSpec]) -> set[str]:
    """이 DAG의 order가 받아야 하는 params 이름 (result에 닿는 첫 단계들의 params 합)."""
    rn, _ = split_ref(dag.result)
    inc = incoming(dag)
    names: set[str] = set()
    for n in ancestors(dag, rn):
        if not inc.get(n):
            node = dag.nodes[n]
            spec = actions.get((node.service, node.action))
            if spec:
                names |= set(spec.params)
    return names

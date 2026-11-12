from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ms_dataflow import ids
from ms_dataflow.planner import InFlight, plan
from ms_dataflow.project import load_project

FIXTURES = Path(__file__).parent / "fixtures"


class FakeTable:
    """가짜 캐시. 쓰기 메서드가 없으므로 Planner가 쓰려 하면 AttributeError가 난다."""

    def __init__(self) -> None:
        self.cache: dict[str, tuple[dict[str, str], float]] = {}
        self.running: dict[str, InFlight] = {}

    def fresh(self, step_key, outputs, fresh_for: timedelta | None, now):
        hit = self.cache.get(step_key)
        if hit is None:
            return None
        ids_, created = hit
        if fresh_for is not None and now - created >= fresh_for.total_seconds():
            return None
        return ids_

    def inflight(self, step_key):
        return self.running.get(step_key)


def setup():
    p = load_project(FIXTURES / "calc")
    return p.dags["number"], p.registry.actions


def remember(table: FakeTable, result, created: float) -> None:
    for s in result.steps:
        table.cache[s.step_key] = ({k: a for k, (_, a) in s.outputs.items()}, created)


def test_empty_cache_plans_all_steps():
    dag, actions = setup()
    r = plan(dag, actions, {"n": 3}, FakeTable(), now=100.0)
    assert [s.node for s in r.steps] == ["make", "add", "double"]
    assert r.steps[0].params == {"n": 3} and r.steps[1].params == {}
    assert r.steps[1].deps == ["self:1"] and r.steps[2].deps == ["self:2"]
    assert r.result_ref == "self:3"
    assert r.result_artifact == r.steps[2].outputs["out"][1]


def test_full_cache_plans_nothing():
    dag, actions = setup()
    table = FakeTable()
    first = plan(dag, actions, {"n": 3}, table, now=100.0)
    remember(table, first, 100.0)
    again = plan(dag, actions, {"n": 3}, table, now=200.0)
    assert again.steps == []
    assert again.result_artifact == first.result_artifact
    assert again.result_lineage == first.result_lineage
    assert again.result_ref is None


def test_version_change_replans_from_that_step():
    dag, actions = setup()
    table = FakeTable()
    remember(table, plan(dag, actions, {"n": 3}, table, now=100.0), 100.0)
    changed = dict(actions)
    changed[("mid", "add")] = actions[("mid", "add")].model_copy(update={"version": "new"})
    r = plan(dag, changed, {"n": 3}, table, now=200.0)
    assert [s.node for s in r.steps] == ["add", "double"]
    assert r.cached == ["make"]
    assert r.steps[0].deps == []  # make는 캐시 히트라 의존할 단계가 없다


def test_fresh_for_expiry_replans_from_source():
    dag, actions = setup()
    dag = dag.model_copy(
        update={
            "nodes": {
                **dag.nodes,
                "make": dag.nodes["make"].model_copy(update={"fresh_for": timedelta(seconds=10)}),
            }
        }
    )
    table = FakeTable()
    remember(table, plan(dag, actions, {"n": 3}, table, now=100.0), 100.0)
    assert plan(dag, actions, {"n": 3}, table, now=105.0).steps == []
    r = plan(dag, actions, {"n": 3}, table, now=111.0)
    assert [s.node for s in r.steps] == ["make", "add", "double"]


def test_joins_inflight_step():
    dag, actions = setup()
    table = FakeTable()
    first = plan(dag, actions, {"n": 3}, table, now=100.0)
    make = first.steps[0]
    table.running[make.step_key] = InFlight(
        "run1:1", make.generation, {k: a for k, (_, a) in make.outputs.items()}
    )
    r = plan(dag, actions, {"n": 3}, table, now=101.0)
    assert r.joined == ["make"]
    assert [s.node for s in r.steps] == ["add", "double"]
    assert r.steps[0].deps == ["run1:1"]


def test_different_params_are_different_requests():
    dag, actions = setup()
    a = plan(dag, actions, {"n": 3}, FakeTable(), now=100.0)
    b = plan(dag, actions, {"n": 4}, FakeTable(), now=100.0)
    assert a.result_lineage != b.result_lineage


def test_result_lineage_does_not_depend_on_time():
    dag, actions = setup()
    a = plan(dag, actions, {"n": 3}, FakeTable(), now=100.0)
    b = plan(dag, actions, {"n": 3}, FakeTable(), now=999.0)
    assert a.result_lineage != ""  # lineage는 부모 artifact_id를 통해 generation을 품는다
    assert ids.lineage_key(a.steps[0].step_key, "out") == ids.lineage_key(
        b.steps[0].step_key, "out"
    )

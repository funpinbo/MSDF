"""ID 결정성 테스트. 여기가 깨지면 캐시가 조용히 잘못된 데이터를 돌려준다."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from ms_dataflow import ids
from ms_dataflow.resolvers.file import FileResolver

slot_names = st.text("abcdefgh_", min_size=1, max_size=6)
artifact = st.text("0123456789abcdef", min_size=8, max_size=8)


@given(st.dictionaries(slot_names, artifact, max_size=5))
def test_lineage_key_is_deterministic(inputs):
    a = ids.step_key("svc", "act", "v1", inputs, {"q": 1})
    b = ids.step_key("svc", "act", "v1", dict(inputs), {"q": 1})
    assert a == b
    assert ids.lineage_key(a, "out") == ids.lineage_key(b, "out")


@given(st.dictionaries(slot_names, artifact, min_size=2, max_size=5))
def test_lineage_key_ignores_slot_order(inputs):
    reversed_inputs = dict(reversed(list(inputs.items())))
    assert ids.step_key("s", "a", "v", inputs) == ids.step_key("s", "a", "v", reversed_inputs)


def test_lineage_key_differs_by_slot_name():
    assert ids.step_key("s", "a", "v", {"x": "id1"}) != ids.step_key("s", "a", "v", {"y": "id1"})


def test_lineage_key_differs_by_output_slot():
    k = ids.step_key("s", "a", "v", {})
    assert ids.lineage_key(k, "summary") != ids.lineage_key(k, "keywords")


def test_params_are_canonical():
    a = ids.step_key("s", "a", "v", {}, {"a": 1, "b": [1, 2]})
    b = ids.step_key("s", "a", "v", {}, {"b": [1, 2], "a": 1})
    assert a == b
    assert a != ids.step_key("s", "a", "v", {}, {"a": 2, "b": [1, 2]})


def test_planned_id_matches_resolver_issued_id(tmp_path):
    step = ids.step_key("s", "a", "v", {"x": "p1"})
    gen = 1700000000.123456
    planned = ids.planned_id(["p2", "p1"], step, "out", gen)
    saved = FileResolver(str(tmp_path)).save(
        ids.lineage_key(step, "out"), gen, {"a": 1}, ["p1", "p2"]
    )
    assert saved.artifact_id == planned


def test_version_ignores_comments_and_whitespace():
    a = '''
def f(x):
    """문서"""
    # 주석
    return x + 1
'''
    b = """
@action(retries=3)
def f(x):

    return x+1   # 다른 주석
"""
    assert ids.version_of_source(a) == ids.version_of_source(b)


def test_version_changes_with_logic():
    a = "def f(x):\n    return x + 1\n"
    b = "def f(x):\n    return x + 2\n"
    assert ids.version_of_source(a) != ids.version_of_source(b)

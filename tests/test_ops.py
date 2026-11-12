"""M4: 삭제 요청과 보관 정책(hot/cold)."""

from __future__ import annotations

import json
import textwrap
import time

import pytest
from conftest import clear_log, read_log

from ms_dataflow import delete as public_delete
from ms_dataflow import ops
from ms_dataflow.errors import OrderError, PermissionDenied
from ms_dataflow.execute.local import LocalRunner
from ms_dataflow.models import Settings
from ms_dataflow.resolvers.file import FileResolver

IAM = """
layers:
  account: {kind: ordered, levels: [viewer, analyst, admin]}
rules:
  - {type: order, account: any, service: req}
  - {type: flow, from: "*", to: "*", account: any}
  - {type: delete, account: ">=admin", service: req, target: "mid.double.*"}
"""


def events(root):
    return [e for e, _ in read_log(root)]


def outputs(r, run_id):
    return {
        s["action"]: json.loads(s["outputs"])
        for s in r.engine.steps(run_id)
        if s["outputs"] != "{}"
    }


def test_delete_tombstones_then_removes_body(calc):
    (calc / "iam.yaml").write_text(textwrap.dedent(IAM))
    with LocalRunner(calc) as r:
        key = r.order("number", {"n": 3}, requester="req", context={"account": "admin"})
        r.run_until_idle()
        aid = r.last.plan.result_artifact
        out = r.engine.delete("req", {"account": "admin"}, key)
        assert out == {"deleted": [aid], "pending": 0}
        tomb = r.store.query("SELECT * FROM artifact_tombstone WHERE artifact_id = ?", (aid,))[0]
        assert tomb["reason"] == "requested" and tomb["body_deleted"] == 1
        assert tomb["account"] == "admin" and tomb["service"] == "req"
        assert not list((calc / ".msdf" / "store").rglob(f"{aid}*"))

        # 같은 요청이 오면 지운 단계만 다시 만든다 (상위는 캐시)
        clear_log(calc)
        r.order("number", {"n": 3}, requester="req", context={"account": "admin"})
        r.run_until_idle()
        assert events(calc) == ["double", "on_done"]


def test_delete_is_checked_by_iam(calc):
    (calc / "iam.yaml").write_text(textwrap.dedent(IAM))
    with LocalRunner(calc) as r:
        key = r.order("number", {"n": 3}, requester="req", context={"account": "viewer"})
        r.run_until_idle()
        with pytest.raises(PermissionDenied) as e:
            r.engine.delete("req", {"account": "analyst"}, key)
        assert e.value.blocked == ["delete: req → mid.double.out"]


def test_cascade_deletes_descendants(calc):
    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        outs = outputs(r, r.last.run_id)
        make_key = outs["make"]["out"]["lineage_key"]
        out = r.engine.delete("req", {}, make_key, cascade=True)
        expected = {outs[a]["out"]["artifact_id"] for a in ("make", "add", "double")}
        assert set(out["deleted"]) == expected
        roots = r.store.query(
            "SELECT cascade_root FROM artifact_tombstone WHERE cascade_root IS NOT NULL"
        )
        assert {row["cascade_root"] for row in roots} == {outs["make"]["out"]["artifact_id"]}


def test_delete_without_cascade_keeps_children(calc):
    with LocalRunner(calc) as r:
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        outs = outputs(r, r.last.run_id)
        r.engine.delete("req", {}, outs["make"]["out"]["lineage_key"])
        trace = ops.lineage(r.engine, outs["double"]["out"]["artifact_id"])
        assert trace["deleted"] is None
        grand = trace["parents"][0]["parents"][0]
        assert grand["deleted"]["reason"] == "requested"  # 추적에서는 "부모 삭제됨"으로 보인다


def test_failed_body_delete_is_retried(calc, monkeypatch):
    calls = {"n": 0}
    original = FileResolver.delete

    def flaky(self, artifact_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("디스크 오류")
        original(self, artifact_id)

    monkeypatch.setattr(FileResolver, "delete", flaky)
    with LocalRunner(calc) as r:
        key = r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert r.engine.delete("req", {}, key)["pending"] == 1
        # 표시가 먼저 되었으므로 본체가 남아 있어도 캐시로 쓰이지 않는다
        clear_log(calc)
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        assert "double" in events(calc)
        assert r.engine.purge() == 0


def test_delete_unknown_key(calc):
    with LocalRunner(calc) as r, pytest.raises(OrderError, match="지울 데이터가 없습니다"):
        r.engine.delete("req", {}, "nope")


def test_public_delete_needs_engine():
    with pytest.raises(OrderError, match="start"):
        public_delete("x")


def test_old_generations_move_to_cold(calc):
    dag = calc / "dags" / "number.yaml"
    dag.write_text(dag.read_text().replace("action: make}", "action: make, fresh_for: 50ms}"))
    with LocalRunner(calc, settings=Settings(keep_generations=2)) as r:
        for _ in range(3):
            r.order("number", {"n": 3}, requester="req")
            r.run_until_idle()
            time.sleep(0.06)
        make_lk = outputs(r, r.last.run_id)["make"]["out"]["lineage_key"]
        hot = r.store.query("SELECT id FROM artifact WHERE lineage_key = ?", (make_lk,))
        cold = r.store.query("SELECT id FROM cold.artifact WHERE lineage_key = ?", (make_lk,))
        assert len(hot) == 2 and len(cold) == 1
        # 하위 Artifact도 함께 cold로 간다
        assert r.store.query("SELECT count(*) AS n FROM cold.artifact")[0]["n"] == 3
        # 계보 연결은 옮기지 않으므로 cold의 것도 추적할 수 있다
        trace = ops.lineage(r.engine, cold[0]["id"])
        assert trace["tier"] == "cold"


def test_old_versions_move_to_cold(calc):
    db = calc.parent / "meta.db"
    mid = calc / "mid.py"
    for i in range(3):
        mid.write_text(mid.read_text().replace(f'x["value"] + {i + 1}', f'x["value"] + {i + 2}'))
        with LocalRunner(calc, db=db, settings=Settings(keep_versions=2)) as r:
            r.order("number", {"n": 3}, requester="req")
            r.run_until_idle()
    with LocalRunner(calc, db=db) as r:
        hot = r.store.query("SELECT DISTINCT version FROM artifact WHERE action = 'add'")
        cold = r.store.query("SELECT DISTINCT version FROM cold.artifact WHERE action = 'add'")
        assert len(hot) == 2 and len(cold) == 1
        make = r.store.query("SELECT count(*) AS n FROM artifact WHERE action = 'make'")
        assert make[0]["n"] == 1  # 상위(make)는 그대로 hot

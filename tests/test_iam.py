from __future__ import annotations

import textwrap

import pytest

from ms_dataflow.errors import ConfigError, LoadError, PermissionDenied
from ms_dataflow.execute.local import LocalRunner
from ms_dataflow.project import load_project

IAM = """
layers:
  account: {kind: ordered, levels: [viewer, analyst, admin]}
  service: {kind: flat, members: [req, src, mid]}
rules:
  - {type: order, account: ">=analyst", service: req}
  - {type: flow, from: src.make, to: mid.add, account: ">=analyst"}
  - {type: flow, from: mid.*, to: mid.*, account: ">=analyst"}
  - {type: flow, from: mid.double, to: req.on_done, account: any}
  - {type: delete, account: ">=admin", service: req, target: "mid.double.*"}
"""


def write_iam(root, text=IAM):
    (root / "iam.yaml").write_text(textwrap.dedent(text))


def test_allowed_account_runs(calc):
    write_iam(calc)
    with LocalRunner(calc) as r:
        r.order("number", {"n": 1}, requester="req", context={"account": "admin"})
        r.run_until_idle()
        assert r.engine.run(r.last.run_id)["status"] == "done"


def test_low_account_is_denied_with_blocked_edges(calc):
    write_iam(calc)
    with LocalRunner(calc) as r, pytest.raises(PermissionDenied) as e:
        r.order("number", {"n": 1}, requester="req", context={"account": "viewer"})
    assert "order: req → number" in e.value.blocked
    assert "flow: src.make → mid.add" in e.value.blocked
    assert "flow: mid.add → mid.double" in e.value.blocked
    assert not any("on_done" in b for b in e.value.blocked)  # any 규칙


def test_missing_context_value_is_denied(calc):
    write_iam(calc)
    with LocalRunner(calc) as r, pytest.raises(PermissionDenied):
        r.order("number", {"n": 1}, requester="req", context={})


def test_cached_steps_are_still_checked(calc):
    write_iam(calc)
    with LocalRunner(calc) as r:
        r.order("number", {"n": 1}, requester="req", context={"account": "admin"})
        r.run_until_idle()
        with pytest.raises(PermissionDenied):  # 전부 캐시여도 경로 전체를 검사한다
            r.order("number", {"n": 1}, requester="req", context={"account": "viewer"})


def test_delivery_edge_is_checked(calc):
    write_iam(
        calc, IAM.replace("  - {type: flow, from: mid.double, to: req.on_done, account: any}\n", "")
    )
    with LocalRunner(calc) as r, pytest.raises(PermissionDenied) as e:
        r.order("number", {"n": 1}, requester="req", context={"account": "admin"})
    assert e.value.blocked == ["flow: mid.double → req.on_done"]


def test_flow_rule_needs_account(calc):
    write_iam(calc, IAM.replace('to: mid.add, account: ">=analyst"}', "to: mid.add}"))
    with pytest.raises(LoadError) as e:
        load_project(calc)
    assert "account: any" in str(e.value)


def test_bad_level_and_unknown_layer(calc):
    write_iam(calc, IAM.replace('">=analyst", service: req}', '">=boss", tenant: x, service: req}'))
    with pytest.raises(LoadError) as e:
        load_project(calc)
    msg = str(e.value)
    assert "boss" in msg and "tenant" in msg


def test_unknown_rule_type(calc):
    write_iam(calc, IAM + "  - {type: read}\n")
    with pytest.raises(ConfigError):
        load_project(calc)


def test_delete_rule_and_context_keys(calc):
    write_iam(calc)
    iam = load_project(calc).iam
    assert iam.delete_allowed("req", {"account": "admin"}, "mid.double.out")
    assert not iam.delete_allowed("req", {"account": "analyst"}, "mid.double.out")
    assert not iam.delete_allowed("req", {"account": "admin"}, "mid.add.out")
    assert iam.required_context() == ["account"]
    assert iam.missing_context_keys(("tenant",)) == ["account"]
    assert iam.missing_context_keys(None) == []


def test_context_function_is_used_by_order(calc):
    write_iam(calc)
    from ms_dataflow import context
    from ms_dataflow.decorators import _CONTEXT

    role = {"account": "viewer"}

    @context
    def who():
        return dict(role)

    try:
        with LocalRunner(calc) as r:
            with pytest.raises(PermissionDenied):
                r.order("number", {"n": 1}, requester="req")
            role["account"] = "analyst"
            r.order("number", {"n": 1}, requester="req")
    finally:
        _CONTEXT.clear()


def test_registration_rejects_missing_context_keys(calc):
    from fastapi import HTTPException

    from ms_dataflow.execute.scheduler import Scheduler
    from ms_dataflow.models import RegisterRequest
    from ms_dataflow.store import Store

    write_iam(calc)
    project = load_project(calc)
    sched = Scheduler(project, Store())
    reg = project.registry
    req = RegisterRequest(
        instance_id="i1",
        address="http://127.0.0.1:1",
        services=(reg.services["req"],),
        actions=tuple(a for a in reg.actions.values() if a.service == "req"),
        context_keys=("tenant",),
    )
    with pytest.raises(HTTPException) as e:
        sched.register(req)
    assert "account" in e.value.detail["message"]
    ok = req.model_copy(update={"context_keys": ("account",)})
    assert sched.register(ok).instance_id == "i1"

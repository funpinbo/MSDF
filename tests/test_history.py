"""0.6: 실행 기록 보관 기간 — 끝난 run/step은 지우고, cache와 살아 있는 구독은 지킨다."""

from __future__ import annotations

from conftest import clear_log, read_log

from ms_dataflow.execute.local import LocalRunner
from ms_dataflow.models import Settings

DAY = 86400


def counts(r):
    q = r.engine.store.query
    return q("SELECT count(*) FROM run")[0][0], q("SELECT count(*) FROM step")[0][0]


def test_old_finished_runs_are_removed_and_cache_survives(calc):
    t = [1_000_000.0]
    with LocalRunner(calc, settings=Settings(keep_history=7 * DAY), sleep=False) as r:
        r.engine.clock = lambda: t[0]
        r.order("number", {"n": 3}, requester="req")
        r.run_until_idle()
        t[0] += 6 * DAY
        r.order("number", {"n": 4}, requester="req")
        r.run_until_idle()
        assert r.engine.purge_history() == 0  # 아직 7일이 안 지남
        t[0] += 2 * DAY  # 첫 run은 8일, 두 번째는 2일 지남
        assert r.engine.purge_history() == 1
        runs, steps = counts(r)
        assert runs == 1 and steps == 4
        assert (
            r.engine.store.query(
                "SELECT count(*) FROM step_dep WHERE run_id NOT IN (SELECT run_id FROM run)"
            )[0][0]
            == 0
        )
        clear_log(calc)
        r.order("number", {"n": 3}, requester="req")  # 지운 run과 같은 요청
        r.run_until_idle()
    assert [e for e, _ in read_log(calc)] == ["on_done"]  # cache는 그대로 (다시 계산하지 않음)


def test_active_subscription_and_unfinished_runs_are_kept(calc):
    t = [1_000_000.0]
    with LocalRunner(
        calc, settings=Settings(keep_history=DAY, refresh_min_gap=0), sleep=False
    ) as r:
        r.engine.clock = lambda: t[0]
        sub = r.order("number", {"n": 3}, requester="req", subscribe=0)
        r.run_until_idle()
        r.order("number", {"n": 5}, requester="req")  # 끝나지 않은 run (실행하지 않음)
        t[0] += 10 * DAY
        assert r.engine.purge_history() == 0
        assert r.engine.run(sub) is not None
        assert r.engine.cancel(sub)["subscription_ended"]  # 구독이 끝나면
        assert r.engine.purge_history() == 1  # 그때 지울 수 있다


def test_zero_keeps_everything_and_batches_are_bounded(calc):
    t = [1_000_000.0]
    with LocalRunner(calc, settings=Settings(keep_history=0), sleep=False) as r:
        r.engine.clock = lambda: t[0]
        for n in range(5):
            r.order("number", {"n": n}, requester="req")
        r.run_until_idle()
        t[0] += 365 * DAY
        assert r.engine.purge_history() == 0
        r.engine.settings = Settings(keep_history=DAY)
        assert r.engine.purge_history(batch=2) == 2
        assert r.engine.purge_history(batch=2) == 2
        assert r.engine.purge_history(batch=2) == 1
        assert counts(r) == (0, 0)


def test_cli_parses_keep_history():
    from ms_dataflow.cli import _history_seconds

    assert _history_seconds("7d") == 7 * DAY
    assert _history_seconds("12h") == 12 * 3600
    assert _history_seconds("0") == 0 and _history_seconds("forever") == 0

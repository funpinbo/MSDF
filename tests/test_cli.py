from __future__ import annotations

from ms_dataflow.cli import main


def test_check_ok(calc, capsys):
    assert main(["check", "--root", str(calc)]) == 0
    out = capsys.readouterr()
    assert "서비스 3개" in out.out and "Action 5개" in out.out
    assert "iam.yaml이 없어" in out.err


def test_check_reports_errors(calc, capsys):
    dag = calc / "dags" / "number.yaml"
    dag.write_text(dag.read_text().replace("action: double}", "action: triple}"))
    assert main(["check", "--root", str(calc)]) == 1
    err = capsys.readouterr().err
    assert "MSDF 로딩 오류" in err and "triple" in err and "고칠 방법" in err


def test_external_services_are_warnings(calc, capsys):
    (calc / "src.py").unlink()
    assert main(["check", "--root", str(calc)]) == 1
    capsys.readouterr()
    assert main(["check", "--root", str(calc), "--allow-external"]) == 0
    assert "등록될 때 다시 검사" in capsys.readouterr().err


# --- 0.2 ------------------------------------------------------------------
def test_init_creates_runnable_project(tmp_path, capsys):
    from ms_dataflow.execute.local import LocalRunner

    target = tmp_path / "proj"
    assert main(["init", str(target)]) == 0
    assert "msdf up" in capsys.readouterr().out
    assert main(["check", "--root", str(target)]) == 0
    assert "서비스 3개" in capsys.readouterr().out
    with LocalRunner(target) as r:
        r.order("daily_stats", {"day": "2026-11-12"}, requester="app")
        r.run_until_idle()
        assert r.engine.run(r.last.run_id)["status"] == "done"
    assert "결과: {'count': 3, 'total': 15}" in capsys.readouterr().out
    assert main(["init", str(target)]) == 1  # 덮어쓰지 않는다


def test_status_runs_cancel_against_engine(calc, capsys):
    import threading

    import uvicorn
    from test_distributed import free_port, wait_for

    from ms_dataflow.cli import build_app
    from ms_dataflow.models import Order, Settings
    from ms_dataflow.project import load_project

    project = load_project(calc)
    app = build_app(project, str(calc / ".msdf" / "m.db"), Settings(), token="t0k")
    sched = app.state.sched
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    wait_for(lambda: server.started, 10)
    eng = ["--engine", f"http://127.0.0.1:{port}"]
    try:
        try:
            main(["status", *eng])
        except SystemExit as e:
            assert "토큰" in str(e)
        assert main(["status", *eng, "--token", "t0k"]) == 0
        out = capsys.readouterr().out
        assert "src" in out and "연결 안 됨" in out
        assert main(["runs", *eng, "--token", "t0k"]) == 0
        assert "실행 기록이 없습니다" in capsys.readouterr().out
        assert sched is not None
        sched.engine.available = None  # 서비스 없이 접수만 시험한다
        sub = sched.engine.submit(Order(name="number", params={"n": 1}, requester="req"))
        assert main(["runs", *eng, "--token", "t0k"]) == 0
        assert sub.run_id in capsys.readouterr().out
        assert main(["cancel", sub.run_id, *eng, "--token", "t0k"]) == 0
        assert "취소했습니다" in capsys.readouterr().out
        assert main(["cancel", sub.run_id, *eng, "--token", "t0k"]) == 1
    finally:
        server.should_exit = True
        t.join(5)

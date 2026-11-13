"""사용자처럼 처음부터 끝까지: msdf init → check → up(토큰) → 서비스 실행 → 결과 → invalidate → 다시 계산.

다른 테스트가 내부를 검증한다면, 이 테스트는 문서의 '시작하기'가 실제로 되는지 확인한다.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "ms_dataflow.cli"]
TOKEN = "smoke-token"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str, path: str):
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def wait_for(cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return
        except Exception:  # noqa: BLE001 - 아직 안 떴을 수 있다
            pass
        time.sleep(0.2)
    raise AssertionError("시간 안에 조건이 맞지 않았습니다")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    out = subprocess.run([*CLI, "init", str(root)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return root


def test_getting_started_works_end_to_end(project: Path):
    env = {**os.environ, "MSDF_TOKEN": TOKEN, "PYTHONUNBUFFERED": "1"}
    check = subprocess.run([*CLI, "check"], cwd=project, capture_output=True, text=True, env=env)
    assert check.returncode == 0 and "서비스 3개" in check.stdout, check.stderr

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env["MSDF_SCHEDULER"] = url
    procs = [subprocess.Popen([*CLI, "up", "--port", str(port), "--no-ui"], cwd=project, env=env)]
    try:
        wait_for(lambda: get(url, "/health")["ok"])
        for svc in ("source.py", "transform.py"):
            procs.append(subprocess.Popen([sys.executable, svc], cwd=project, env=env))
        wait_for(lambda: len(get(url, "/health")["instances"]) == 2)

        def app() -> str:
            out = subprocess.run(
                [sys.executable, "app.py"],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert out.returncode == 0, out.stderr
            return out.stdout

        assert "결과: {'count': 3, 'total': 15}" in app()
        runs = get(url, "/api/runs")
        assert runs[0]["status"] == "done" and runs[0]["plan"]["steps"] == [
            "load",
            "clean",
            "summarize",
        ]

        assert "결과:" in app()  # 같은 요청 → 전부 cache
        assert get(url, "/api/runs")[0]["plan"]["steps"] == []

        inv = subprocess.run(
            [*CLI, "invalidate", "source.load", "--param", 'day="2026-11-12"'],
            capture_output=True,
            text=True,
            env=env,
        )
        assert inv.returncode == 0, inv.stderr
        assert "결과:" in app()  # source가 바뀜 → 다시 계산
        assert get(url, "/api/runs")[0]["plan"]["steps"] == ["load", "clean", "summarize"]

        status = subprocess.run([*CLI, "status"], capture_output=True, text=True, env=env)
        assert status.returncode == 0 and "source" in status.stdout

        no_token = {k: v for k, v in env.items() if k != "MSDF_TOKEN"}
        denied = subprocess.run([*CLI, "runs"], capture_output=True, text=True, env=no_token)
        assert denied.returncode != 0 and "토큰" in denied.stderr
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

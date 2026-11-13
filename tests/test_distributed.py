"""M2 통합 테스트: msdf 엔진 + 서비스 프로세스 여러 개."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from conftest import read_log

from ms_dataflow.cli import build_app
from ms_dataflow.models import Settings
from ms_dataflow.project import load_project

FAST = Settings(lease_ttl=2.0, heartbeat_every=0.4, reaper_every=0.3)

SERVE = """
import os, sys, time, traceback, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import {svc}
from ms_dataflow import start

def note(event, value):
    with open(os.environ["CALC_LOG"], "a") as f:
        f.write(json.dumps({{"event": event, "value": value}}) + "\\n")

try:
    start(os.environ["MSDF_SCHEDULER"], timeout=20)
except Exception as e:
    note("start_error", type(e).__name__ + ": " + str(e))
    sys.exit(1)
note("started", "{svc}")
for n in [x for x in os.environ.get("TRIGGER", "").split(",") if x]:
    try:
        {svc}.{svc}(int(n))
    except Exception as e:
        note("order_error", type(e).__name__)
    time.sleep(float(os.environ.get("TRIGGER_GAP", "0.5")))
while True:
    time.sleep(1)
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Cluster:
    def __init__(self, root: Path, url: str) -> None:
        self.root = root
        self.url = url
        self.procs: dict[str, subprocess.Popen[bytes]] = {}

    def service(self, svc: str, name: str | None = None, **env: str) -> subprocess.Popen[bytes]:
        script = self.root / f"serve_{svc}.py"
        if not script.exists():
            script.write_text(textwrap.dedent(SERVE.format(svc=svc)))
        e = {**os.environ, "MSDF_SCHEDULER": self.url, **env}
        p = subprocess.Popen([sys.executable, str(script)], env=e, cwd=self.root)
        self.procs[name or svc] = p
        return p

    def wait_started(self, *svcs: str, timeout: float = 20) -> None:
        wait_for(lambda: all(("started", s) in read_log(self.root) for s in svcs), timeout)

    def kill(self, name: str) -> None:
        p = self.procs.pop(name)
        p.send_signal(signal.SIGKILL)
        p.wait()

    def close(self) -> None:
        for p in self.procs.values():
            p.terminate()
        for p in self.procs.values():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


def wait_for(cond: Callable[[], bool], timeout: float = 20) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.1)
    raise AssertionError("시간 안에 조건이 맞지 않았습니다")


def _cluster(calc: Path, token: str | None = None) -> Iterator[Cluster]:
    project = load_project(calc)
    app = build_app(project, str(calc / ".msdf" / "msdf.db"), FAST, ui=False, token=token)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    wait_for(lambda: server.started, 10)
    c = Cluster(calc, f"http://127.0.0.1:{port}")
    yield c
    c.close()
    server.should_exit = True
    t.join(5)


@pytest.fixture
def cluster(calc) -> Iterator[Cluster]:
    yield from _cluster(calc)


@pytest.fixture
def secured(calc) -> Iterator[Cluster]:
    yield from _cluster(calc, token="tok-123")


def events(root):
    return [e for e, _ in read_log(root)]


def test_roundtrip_across_processes_and_cache(cluster):
    cluster.service("src")
    cluster.service("mid")
    cluster.wait_started("src", "mid")
    cluster.service("req", TRIGGER="3,3", TRIGGER_GAP="1.5")
    wait_for(lambda: events(cluster.root).count("on_done") == 2)
    log = read_log(cluster.root)
    assert ("on_done", {"value": 8}) in log
    assert events(cluster.root).count("make") == 1  # 두 번째는 캐시
    health = httpx.get(f"{cluster.url}/health").json()
    assert {s for i in health["instances"] for s in i["services"]} == {"src", "mid", "req"}


def test_killed_worker_step_is_requeued(cluster):
    cluster.service("src")
    cluster.service("mid", name="mid1", CALC_SLOW="add")
    cluster.wait_started("src", "mid")
    cluster.service("req", TRIGGER="5")
    wait_for(lambda: "add" in events(cluster.root))
    cluster.kill("mid1")  # add 실행 중에 죽인다
    cluster.service("mid", name="mid2", CALC_SLOW="add")  # 마커가 있어 두 번째는 빠르다
    wait_for(lambda: "on_done" in events(cluster.root), 30)
    assert ("on_done", {"value": 12}) in read_log(cluster.root)
    assert events(cluster.root).count("add") == 2


def test_missing_service_rejects_order(cluster):
    cluster.service("req", TRIGGER="1")
    wait_for(lambda: "order_error" in events(cluster.root))
    assert ("order_error", "ServiceUnavailable") in read_log(cluster.root)


def test_same_name_with_different_code_is_rejected(cluster):
    cluster.service("mid", name="mid1")
    cluster.wait_started("mid")
    mid = cluster.root / "mid.py"
    mid.write_text(mid.read_text().replace('x["value"] * 2', 'x["value"] * 3'))
    cluster.service("mid", name="mid2")
    wait_for(lambda: "start_error" in events(cluster.root))
    err = next(v for e, v in read_log(cluster.root) if e == "start_error")
    assert err.startswith("RegistrationError") and "다른 코드" in err


def test_two_instances_share_work(cluster):
    cluster.service("src")
    cluster.service("mid", name="mid1")
    cluster.service("mid", name="mid2")
    cluster.wait_started("src")
    wait_for(lambda: events(cluster.root).count("started") == 3)
    cluster.service("req", TRIGGER="1,2,3,4", TRIGGER_GAP="0.1")
    wait_for(lambda: events(cluster.root).count("on_done") == 4)
    values = sorted(v["value"] for e, v in read_log(cluster.root) if e == "on_done")
    assert values == [4, 6, 8, 10]


def test_token_required_between_engine_and_services(secured):
    secured.service("src", MSDF_TOKEN="tok-123")
    secured.service("mid", MSDF_TOKEN="tok-123")
    secured.wait_started("src", "mid")
    secured.service("req", MSDF_TOKEN="tok-123", TRIGGER="4")
    secured.service("req", name="intruder")  # 토큰 없음
    wait_for(lambda: ("on_done", {"value": 10}) in read_log(secured.root))
    wait_for(lambda: any(e == "start_error" for e, _ in read_log(secured.root)))
    errors = [v for e, v in read_log(secured.root) if e == "start_error"]
    assert "토큰" in errors[0]


def test_meta_and_request_id_over_http(cluster):
    req = cluster.root / "req.py"
    req.write_text(
        req.read_text()
        .replace(
            'order("number", params={"n": n})', 'order("number", params={"n": n}, meta={"n": n})'
        )
        .replace(
            'def on_done(result):\n    log("on_done", result)',
            "def on_done(result, meta, request_id):\n"
            '    log("on_done", {"r": result, "meta": meta, "id": request_id})',
        )
    )
    assert "meta, request_id" in req.read_text()
    cluster.service("src")
    cluster.service("mid")
    cluster.wait_started("src", "mid")
    cluster.service("req", TRIGGER="2,3")
    wait_for(lambda: len([e for e, _ in read_log(cluster.root) if e == "on_done"]) == 2)
    got = [v for e, v in read_log(cluster.root) if e == "on_done"]
    assert {g["meta"]["n"] for g in got} == {2, 3}
    assert all(len(g["id"]) == 16 for g in got)


def test_invalidate_over_http_and_cli(cluster, capsys):
    from ms_dataflow.cli import main

    cluster.service("src")
    cluster.service("mid")
    cluster.wait_started("src", "mid")
    cluster.service("req", TRIGGER="9")
    wait_for(lambda: ("on_done", {"value": 20}) in read_log(cluster.root))
    eng = ["--engine", cluster.url]
    assert main(["invalidate", "src.make", "--param", "n=9", *eng]) == 0
    assert "data_version" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        main(["invalidate", "src.nope", *eng])
    assert "nope" in str(e.value)


def test_subscription_is_refreshed_across_processes(cluster):
    data = cluster.root / "data.txt"
    data.write_text("0")
    (cluster.root / "src.py").write_text(
        "import os\nfrom ms_dataflow import action, service\nservice('src')\n"
        "@action(params=['n'], outputs=['out'])\ndef make(n):\n"
        f"    return {{'value': n + int(open({str(data)!r}).read())}}\n"
    )
    req = cluster.root / "req.py"
    req.write_text(
        req.read_text()
        .replace(
            'order("number", params={"n": n})', 'order("number", params={"n": n}, subscribe="10m")'
        )
        .replace(
            'def on_done(result):\n    log("on_done", result)',
            'def on_done(result, refresh, request_id):\n    log("on_done", {"v": result["value"], "refresh": refresh, "id": request_id})',
        )
    )
    cluster.service("src")
    cluster.service("mid")
    cluster.wait_started("src", "mid")
    cluster.service("req", TRIGGER="3")
    wait_for(lambda: any(e == "on_done" for e, _ in read_log(cluster.root)))
    data.write_text("10")  # source 데이터가 바뀜
    r = httpx.post(f"{cluster.url}/api/invalidate", json={"action": "src.make", "params": {"n": 3}})
    assert r.json()["subscriptions"] == 1
    wait_for(lambda: len([e for e, _ in read_log(cluster.root) if e == "on_done"]) == 2)
    first, second = [v for e, v in read_log(cluster.root) if e == "on_done"]
    assert (first["v"], first["refresh"]) == (8, 0)
    assert (second["v"], second["refresh"]) == (28, 1)
    assert first["id"] == second["id"]
    inst = next(
        i for i in httpx.get(f"{cluster.url}/health").json()["instances"] if "req" in i["services"]
    )
    other = next(
        i for i in httpx.get(f"{cluster.url}/health").json()["instances"] if "mid" in i["services"]
    )
    denied = httpx.post(
        f"{cluster.url}/cancel",
        json={"instance_id": other["id"], "requester": "mid", "request_id": first["id"]},
    )
    assert denied.status_code == 400  # 남의 요청은 취소할 수 없다
    ok = httpx.post(
        f"{cluster.url}/cancel",
        json={"instance_id": inst["id"], "requester": "req", "request_id": first["id"]},
    )
    assert ok.json()["subscription_ended"]
    r = httpx.post(f"{cluster.url}/api/invalidate", json={"action": "src.make"})
    assert r.json()["subscriptions"] == 0

import json
import os
import time

from ms_dataflow import action, service


def log(event, value=None):
    with open(os.environ["CALC_LOG"], "a") as f:
        f.write(json.dumps({"event": event, "value": value}) + "\n")


def maybe_fail(name):
    spec = os.environ.get("CALC_FAIL", "")
    if not spec.startswith(name):
        return
    path = os.environ["CALC_LOG"] + ".fail"
    count = 0
    if os.path.exists(path):
        with open(path) as f:
            count = int(f.read())
    limit = int(spec.split(":")[1]) if ":" in spec else 10**9
    if count < limit:
        with open(path, "w") as f:
            f.write(str(count + 1))
        raise RuntimeError(f"{name} 실패 주입 ({count + 1})")


def maybe_slow(name):
    """CALC_SLOW에 이름이 있으면 첫 호출만 오래 걸린다 (프로세스를 죽이는 테스트용)."""
    if os.environ.get("CALC_SLOW") != name:
        return
    marker = os.environ["CALC_LOG"] + ".slow"
    if not os.path.exists(marker):
        with open(marker, "w"):
            pass
        time.sleep(60)


@service("mid")
def mid():
    pass


@action(inputs=["x"], retries=2)
def add(x):
    log("add", x["value"])
    maybe_fail("add")
    maybe_slow("add")
    return {"value": x["value"] + 1}


@action(inputs=["x"])
def double(x):
    log("double", x["value"])
    maybe_fail("double")
    return {"value": x["value"] * 2}

import json
import os

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


@service("mid")
def mid():
    pass


@action(inputs=["x"], retries=2)
def add(x):
    log("add", x["value"])
    maybe_fail("add")
    return {"value": x["value"] + 1}


@action(inputs=["x"])
def double(x):
    log("double", x["value"])
    maybe_fail("double")
    return {"value": x["value"] * 2}

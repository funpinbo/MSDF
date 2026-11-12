import json
import os

from ms_dataflow import action, service


def log(event, value=None):
    with open(os.environ["CALC_LOG"], "a") as f:
        f.write(json.dumps({"event": event, "value": value}) + "\n")


@service("src")
def src():
    pass


@action(params=["n"], outputs=["out"])
def make(n):
    log("make", n)
    return {"value": n}

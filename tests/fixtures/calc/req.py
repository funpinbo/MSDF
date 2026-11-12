import json
import os

from ms_dataflow import action, order, service


def log(event, value=None):
    with open(os.environ["CALC_LOG"], "a") as f:
        f.write(json.dumps({"event": event, "value": value}) + "\n")


@service("req")
def req(n):
    return order("number", params={"n": n})


@action(inputs=["result"])
def on_done(result):
    log("on_done", result)


@action
def on_fail(status):
    log("on_fail", status)

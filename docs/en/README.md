# MSDF documentation

[한국어](../README.md) | **English**

MSDF (Micro Service Data Flow) is a Python framework that lets microservices exchange data **without knowing about each other**.
A service only asks for a result by name ("I need this"); which services produce it, and in what order, is decided by a configuration file (a DAG).

> Current version: **0.3.1**. Runs on one machine as an engine plus several service processes. Not on PyPI yet ([Installation](installation.md)).
> What is done and what is left is in the [roadmap](roadmap.md).
>
> CLI output, error messages and the web UI are currently in Korean.

## Reading order

| Order | Document | For |
| --- | --- | --- |
| – | [Why MSDF](background.md) | People who want to know first why this structure is needed |
| 0 | [Installation](installation.md) | Installing without PyPI: repository, git URL, wheel file |
| 1 | [Getting started](getting-started.md) | Run the example in 5 minutes, then attach MSDF to your project |
| 2 | [Concepts](concepts.md) | What Service, Action, Order, DAG and Artifact mean |
| 3 | [Writing services](writing-services.md) | How to use `service`, `action`, `order`, `start`, `context`, `delete`, `invalidate` |
| 4 | [Configuration](configuration.md) | The three YAML files (DAG, IAM, resolvers) and the `msdf` command |
| 5 | [How it works](how-it-works.md) | How the engine processes a request, and what happens on failure |
| 6 | [Roadmap](roadmap.md) | How far it has come and where it is heading |

## At a glance

```python
# app.py — a service only asks for a result by name
from ms_dataflow import action, order, service

@service("app")
def app(day: str, user: str):
    order("daily_stats", params={"day": day}, meta={"user": user})   # returns immediately with a request_id

@action(inputs=["stats"])
def on_stats(stats, meta):                       # woken up when the result arrives; meta says whose request it was
    print("to", meta["user"], ":", stats)

@action
def on_stats_failed(status: str):                # woken up on final failure
    print("failed:", status)
```

```yaml
# dags/daily_stats.yaml — who produces what, in which order, is decided only here
order: daily_stats
nodes:
  load:      {service: source,    action: load}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}
edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}
result: summarize.stats
deliveries:
  - {requester: app, on_success: app.on_stats, on_fail: app.on_stats_failed}
```

The `app` code never mentions `source` or `transform`, nor which database holds the data.
If the flow changes, edit only the DAG; if the logic changes, edit only that service.

A runnable example is in [`examples/chatbot`](../../examples/chatbot/README.en.md). It works with sample documents, no LLM.

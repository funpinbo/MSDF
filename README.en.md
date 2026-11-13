# MSDF — Micro Service Data Flow

[한국어](README.md) | **English**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Python framework that lets services in a microservice architecture **exchange data without knowing about each other**.

Unlike task-centric tools such as Airflow, the unit of flow is **data (an Artifact)**, not a task.
A service only asks for a result by name; which services produce it, and in what order, is decided by a DAG.

**Why it exists.** When you build a chatbot as an agent, features such as search, embedding and summarization keep getting added, and each time
the chatbot ends up owning "what to call, in which order, where to keep the results, and what to do on failure". On top of that, a chatbot changes
a lot of data. MSDF moves that conductor role out of the features, so they run on data changes without knowing about each other.
Adding or removing a feature then means editing only the DAG. → [Why MSDF](docs/en/background.md)

> Current version **0.3.1**: runs on one machine as an engine plus several service processes. It is not on PyPI yet;
> [install it from the repository or a git URL](docs/en/installation.md). What changed is in the [changelog](CHANGELOG.en.md); remaining work is in the [roadmap](docs/en/roadmap.md).
>
> CLI output, error messages and the web UI are currently in Korean. The bundled example uses Korean sample data.

## Try it quickly

```bash
git clone https://github.com/funpinbo/MSDF.git && cd MSDF
uv sync --all-extras
cd examples/chatbot
uv run python run_local.py "환불은 언제 되나요" "환불은 언제 되나요"
```

The second question is the same request, so no step runs and the answer comes from the cache. To start the engine and the web UI as well,
see [Getting started](docs/en/getting-started.md).

## How you use it

```python
# app.py — only asks for a result by name
from ms_dataflow import action, order, service, start

@service("app")
def app(day: str, user: str):
    # returns immediately. Who gets the result (user) goes in meta; it is not used for computing (cache key)
    order("daily_stats", params={"day": day}, meta={"user": user})

@action(inputs=["stats"])
def on_stats(stats, meta):                       # the DAG's on_success points here
    print("to", meta["user"], ":", stats)

@action
def on_stats_failed(status: str, meta, error):   # the DAG's on_fail points here ("failed" | "cancelled")
    print("to", meta["user"], ": failed", status, error)

if __name__ == "__main__":
    start()        # attaches to the engine (returns immediately)
    app("2026-11-12", "alice")
```

```python
# transform.py — declares only its own work
from ms_dataflow import action, service, start

service("transform")

@action(inputs=["rows"], outputs=["clean"], retries=2)
def clean(rows): return [r for r in rows if r["value"] is not None]

@action(inputs=["rows"], outputs=["stats"])
def summarize(rows): return {"count": len(rows), "total": sum(r["value"] for r in rows)}

if __name__ == "__main__":
    start(block=True)   # a service that only provides Actions waits until Ctrl+C
```

```python
# source.py — when source data changes, the service that reads it announces it (it does not know who depends on it)
invalidate("load", params={"day": "2026-11-12"})   # from the next request, only load and its downstream steps recompute
```

```yaml
# dags/daily_stats.yaml — the wiring changes only here
order: daily_stats
nodes:
  load:      {service: source,    action: load, fresh_for: 1h}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}
edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}
result: summarize.stats
deliveries:
  - {requester: app, on_success: app.on_stats, on_fail: app.on_stats_failed}
```

```bash
msdf check           # validate code and configuration
msdf up              # start the engine (Scheduler + DB + web UI)
python source.py     # run services as usual; start() attaches them to the engine
python transform.py
python app.py
```

All you use is seven names — `service`, `action`, `order`, `start`, `context`, `delete`, `invalidate` — and three YAML files.
Data IDs, cache keys, queues, leases and serialization are handled by the engine and never appear in your code.

## What gets better

1. **Free choice of storage.** Change only `resolvers.yaml`. Service code does not know which database is used.
2. **Minimal change surface.** If logic changes, edit the service; if the flow changes, edit the DAG.
3. **Data provenance at a glance.** Every Artifact carries its lineage: source data, service, Action and version.
4. **Permissions in one place.** One IAM rule file checks every flow.
5. **The same request is never recomputed.** Change the logic and only that step onward is recomputed.
6. **Restart from where it failed.** Each step is stored, and work from a dead Worker is picked up by another instance.
7. **Results reach exactly who asked.** `order()` returns a request_id and deliveries get back your `meta` (e.g. a session_id). Many users asking the same question: computed once, answered to each.
8. **When data changes, recompute from where it changed.** When the service that reads the data calls `invalidate()`, only that step and its downstream steps are recomputed.

## What it does not do

- It does not manage whole services. Context inside a service, and how it waits for results, are up to the author.
- It does not guarantee idempotency. Producing the same result for the same input is the service's responsibility.
- It does not manage databases. It sends save and delete requests; how long data is kept is up to your database design.

## Architecture

```
          msdf up (engine process)
   ┌──────────────────────────────┐
   │  Scheduler + Planner + IAM   │
   │  SQLite (single writer)      │
   │  web UI (/ui)                │
   └──┬────────────┬──────────┬───┘
      │            │          │        HTTP both ways
  ┌───┴────┐  ┌────┴─────┐  ┌─┴───────┐
  │  app   │  │  source  │  │transform│   each process = that service's Worker
  │+start()│  │ +start() │  │+start() │
  └────────┘  └──────────┘  └─────────┘
```

Data itself moves only between service processes and storage. The engine only says "where to put it" and never relays the data.

## Documentation

| Document | Contents |
| --- | --- |
| [Why MSDF](docs/en/background.md) | How a chatbot ends up owning all the logic, and MSDF's approach |
| [Installation](docs/en/installation.md) | Three ways to install without PyPI (repository, git URL, wheel) |
| [Getting started](docs/en/getting-started.md) | Run the example in 5 minutes, then attach MSDF to your project |
| [Concepts](docs/en/concepts.md) | Service, Action, Order, DAG, Artifact, caching and failure handling |
| [Writing services](docs/en/writing-services.md) | How to use `service`, `action`, `order`, `start`, `context`, `delete`, `invalidate` |
| [Configuration](docs/en/configuration.md) | DAG, IAM and resolvers YAML, load-time validation, the `msdf` command |
| [How it works](docs/en/how-it-works.md) | Processes, step execution, failure handling, retention and deletion |
| [Roadmap](docs/en/roadmap.md) | Current status, direction, what comes next |
| [Changelog](CHANGELOG.en.md) | What changed in each version |

Example: [`examples/chatbot`](examples/chatbot/README.en.md) — four services wired together with sample documents, no LLM.

## Installation

**MSDF is not on PyPI yet.** Install from the repository where the engine runs, and from a git URL for services in other repositories.

```bash
# where the engine runs (includes the web UI)
git clone https://github.com/funpinbo/MSDF.git && cd MSDF
uv sync --all-extras                     # with pip: pip install -e ".[server]"

# services in other repositories
pip install "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git"
```

| Extra | Use |
| --- | --- |
| (none) | decorators, models, `msdf check` |
| `runtime` | services that attach to the engine with `start()` |
| `server` | `msdf up` (Scheduler + web UI) |
| `dataframe` | store DataFrames as Parquet |

Python 3.11 or later. The package name is `msdf`; the import name is always `ms_dataflow`. For pinning a version and building a wheel,
see [Installation](docs/en/installation.md).

## Building the web UI

`msdf up` serves the web UI at `http://127.0.0.1:8787/ui`. **Only the UI source is in the repository, not the build output.**
Build it once after cloning (Node.js 20.19 or later, 22 recommended).

```bash
cd frontend
npm install
npm run build        # output: ms_dataflow/ui/dist
```

Without a build the engine and API still work, and `/ui` shows these commands. Where MSDF was installed from a git URL, point to a built folder
with `msdf up --ui-dist PATH`. See [frontend/README.en.md](frontend/README.en.md) for the screens.

| Page | What it does |
| --- | --- |
| Live map | Services, Actions and data flow on one graph, with success, failure and cache counts |
| DAG editor | Build and save DAGs n8n-style by dragging Action nodes onto a canvas and connecting them |
| Logs | Runs, steps, services, DAGs and engine logs, each on its own tab. Failure causes and data lineage. Cancel a running run |
| Permissions | Edit and save IAM layers and rules as tables. Try whether a request would pass |

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy ms_dataflow
```

See [CONTRIBUTING.en.md](CONTRIBUTING.en.md) for how to contribute.

## Security

By default the engine listens only on `127.0.0.1`, without authentication. When you open it to other machines (`--host 0.0.0.0`), **use a token**:
`msdf up --token SECRET` (or `MSDF_TOKEN`). Services, the web UI and the CLI must then all send the same value ([Configuration › Engine token](docs/en/configuration.md#engine-token)).
The token does not encrypt traffic, so on an untrusted network put the engine behind an HTTPS proxy or an SSH tunnel. The web UI's DAG editor and
Permissions page can modify the `dags/` and `iam.yaml` files on the engine machine.

## License

MIT. See [LICENSE](LICENSE).

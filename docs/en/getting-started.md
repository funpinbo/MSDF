# Getting started

[한국어](../getting-started.md) | **English**

This guide has two parts.

1. **Run the example in 5 minutes** — start the chatbot example in the repository (it works with sample documents, no LLM) together with the engine.
2. **Attach MSDF to your project** — build and connect three services yourself.

MSDF is not on PyPI yet. Installation options are in [Installation](installation.md); this guide installs from the repository.

## 1. Run the example in 5 minutes

### Setup

```bash
git clone https://github.com/funpinbo/MSDF.git
cd MSDF
uv sync --all-extras                       # with pip: pip install -e ".[server]"
(cd frontend && npm install && npm run build)   # web UI (Node.js 20.19+)
```

> `uv run` below means "run inside the repository's virtual environment". If you installed with pip, activate the virtual environment and drop `uv run`.

### In a single process

```bash
cd examples/chatbot
uv run python run_local.py "환불은 언제 되나요" "배송 조회는 어디서" "환불은 언제 되나요"
```

The sample documents and questions are in Korean ("When will I get a refund?", "Where can I track my delivery?").

```text
> 환불은 언제 되나요
[챗봇] 환불 정책: 구매 후 7일 이내에는 전액 환불됩니다.
  실행한 단계: fetch, embed, refine
...
> 환불은 언제 되나요
[챗봇] 환불 정책: 구매 후 7일 이내에는 전액 환불됩니다.
  실행한 단계: 없음 (캐시: fetch, embed, refine)
```

`실행한 단계` is "steps executed". When the same question is asked again, none of the three steps run (`없음 (캐시: …)` = "none (cached: …)")
and the answer comes from stored results.

> `run_local.py` runs its own engine and DB inside its process and then exits, so **it does not show up in the web UI of `msdf up`.**
> To see it in the UI, start the engine and attach the services to it, as below.

### Watch it in the web UI

Open two terminals in the `examples/chatbot` folder.

```bash
uv run msdf up                      # terminal 1 — engine (Scheduler + DB + web UI)
```

```bash
uv run python run_services.py       # terminal 2 — attaches the four services and sends a sample question every 3 seconds
```

Open `http://127.0.0.1:8787/ui` and runs start piling up right away. Ctrl+C stops all services.

### Engine and each service as its own process

This is how it looks in real use: every service runs in its own process. Open five terminals in the `examples/chatbot` folder.

```bash
uv run msdf up                  # terminal 1 — engine (Scheduler + DB + web UI)
```

```bash
uv run python search.py         # terminal 2
```

```bash
uv run python embedding.py      # terminal 3
```

```bash
uv run python processing.py     # terminal 4
```

```bash
uv run python chatbot.py        # terminal 5 — type questions here
```

Open `http://127.0.0.1:8787/ui` in a browser. If the engine runs on a remote server or VM, first open a tunnel from your computer with
`ssh -L 8787:127.0.0.1:8787 user@server`, then open the same address ([Troubleshooting](installation.md#troubleshooting)).

- **Live map**: the four services, the data flow, and per-step success, failure and cache counts, refreshed every 2 seconds.
- **DAG editor**: view and edit the `search_result` DAG as a graph.
- **Logs**: each question is recorded as a run, with the time and errors of every step.

Stop `embedding.py` with Ctrl+C while it is working and start it again: the step it was running is reassigned and continues.

## 2. Attach MSDF to your project

The example is "read a day's data (`source`) → clean and aggregate it (`transform`) → return it to whoever asked (`app`)".

> **Shortcut**: `msdf init my_project` creates files laid out like the ones below (iam.yaml included). Then `cd my_project` and skip to [Run](#run).

### Project layout

```text
my_project/
├── source.py
├── transform.py
├── app.py
├── dags/
│   └── daily_stats.yaml
├── iam.yaml          # optional (without it, no permission checks)
└── resolvers.yaml    # optional (without it, data is stored as files in .msdf/store)
```

To install MSDF, see [Installation](installation.md). If this project is a separate repository,
`pip install "msdf[server] @ git+https://github.com/funpinbo/MSDF.git"` also works.

### Write the services

Each service declares only its own work. `inputs`, `outputs` and `params` are names (slots) that mean something only inside that function.

```python
# source.py
from ms_dataflow import action, service, start

service("source")

@action(params=["day"], outputs=["rows"], fresh_for="1h")
def load(day: str) -> list:
    # in real code, read from a database or an external API
    return [{"day": day, "value": v} for v in (3, None, 7, 5)]

if __name__ == "__main__":
    start(block=True)   # attach to the engine and process steps until Ctrl+C
```

```python
# transform.py
from ms_dataflow import action, service, start

service("transform")

@action(inputs=["rows"], outputs=["clean"], retries=2)
def clean(rows: list) -> list:
    return [r for r in rows if r["value"] is not None]

@action(inputs=["rows"], outputs=["stats"])
def summarize(rows: list) -> dict:
    values = [r["value"] for r in rows]
    return {"count": len(values), "total": sum(values)}

if __name__ == "__main__":
    start(block=True)
```

```python
# app.py
import time

from ms_dataflow import action, order, service, start

@service("app")
def app(day: str):
    order("daily_stats", params={"day": day})   # returns immediately; does not wait for the result

@action(inputs=["stats"])
def on_stats(stats: dict):
    print("결과:", stats)

@action
def on_stats_failed(status: str):   # "failed" or "cancelled"
    print("실패:", status)

if __name__ == "__main__":
    start()                          # attach to the engine (returns immediately)
    app("2026-11-12")
    time.sleep(3)                    # a real service would keep running its own server (app.run() etc.)
```

`start()` returns immediately, so a service with its own main loop (such as a web server) just runs it afterwards as usual.
A service that only provides Actions keeps the process alive with `start(block=True)`.

### Connect the flow (DAG)

The wiring between services goes into a DAG file, not into code. Building it by dragging nodes in the web UI's DAG editor saves the same file.

```yaml
# dags/daily_stats.yaml
order: daily_stats               # the name app asks for

nodes:
  load:      {service: source,    action: load}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}

edges:
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}

result: summarize.stats          # the slot returned to app

deliveries:
  - requester: app
    on_success: app.on_stats
    on_fail:    app.on_stats_failed   # required
```

### Validate

```bash
msdf check
```

It reads the code and configuration and reports every problem at once. For example, if the DAG points to an Action that does not exist
(messages are in Korean: node 'clean': service 'transform' has no Action 'cleaning' / how to fix: existing Actions are clean, summarize):

```text
MSDF 로딩 오류: dags/daily_stats.yaml
  노드 'clean': 서비스 'transform'에 Action 'cleaning'이 없습니다.
  고칠 방법: 있는 Action: clean, summarize
```

### Run

```bash
msdf up                  # terminal 1 — engine
python source.py         # terminal 2
python transform.py      # terminal 3
python app.py            # terminal 4
```

`msdf up` reads and validates the configuration, then starts only the engine. Services run as usual and `start()` attaches each process to the engine.
It worked if `app.py` prints `결과: {'count': 3, 'total': 15}`.

If the engine runs on another address, tell the services with `start("http://host:port")` or the `MSDF_SCHEDULER` environment variable.

### Check

- See the flow, the counts and the logs at `http://127.0.0.1:8787/ui`. From a terminal: `msdf status`, `msdf runs`.
- **Request the same day again** and the stored result comes back without re-running the three steps (`load` for one hour).
- Change the logic of `summarize` and restart `transform.py`: the results of `load` and `clean` are reused and computation restarts at `summarize`.
  Changing only comments or whitespace is not treated as a logic change.
- Kill `transform.py` mid-run and start it again: the step it was running is reassigned and continues.
- Announce that the source data changed: `msdf invalidate source.load --param day='"2026-11-12"'` (or `invalidate("load", params={"day": ...})` inside `source.py`).
  The next request recomputes `load`, `clean` and `summarize`.

### Add permissions (optional)

With an `iam.yaml`, the default becomes **deny** and only what you allow passes.

```yaml
# iam.yaml
rules:
  - {type: order, service: app}
  - {type: flow, from: source.load,         to: transform.clean}
  - {type: flow, from: transform.clean,     to: transform.summarize}
  - {type: flow, from: transform.summarize, to: app.on_stats}
```

For layers such as account levels, see [Configuration](configuration.md#iam-file).

### Test in a single process

In tests you can use `LocalRunner`, which runs the engine and the services in one process.

```python
from ms_dataflow.execute.local import LocalRunner

with LocalRunner("my_project") as runner:
    runner.order("daily_stats", {"day": "2026-11-12"}, requester="app")
    runner.run_until_idle()
```

## Next

- To sort out the concepts → [Concepts](concepts.md)
- Every option of the decorators and functions → [Writing services](writing-services.md)
- Engine commands and YAML syntax → [Configuration](configuration.md)

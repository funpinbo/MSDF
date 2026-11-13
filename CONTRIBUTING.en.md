# Contributing

[한국어](CONTRIBUTING.md) | **English**

Current version: **0.3.0.** What comes next is listed under "What comes next" in [docs/en/roadmap.md](docs/en/roadmap.md).

## Getting started

```bash
git clone https://github.com/funpinbo/MSDF
cd MSDF
uv sync --all-extras
uv run pytest
cd frontend && npm install && npm run build   # web UI (do not commit the build output)
```

## Read first

1. [docs/en/concepts.md](docs/en/concepts.md) — what it does
2. [docs/en/how-it-works.md](docs/en/how-it-works.md) — how it works
3. [docs/en/roadmap.md](docs/en/roadmap.md) — where it is and where it is heading

To change documented behaviour, please open an issue first. Many decisions are coupled: changing one changes another.

Documentation is kept in Korean (`docs/`) and English (`docs/en/`). When you change one, please update the other too.

## Code map

| Location | Contents |
| --- | --- |
| `ms_dataflow/decorators.py` | user API: `service`, `action`, `order`, `context`, `delete` |
| `ms_dataflow/client.py` | `start()`, HTTP to the engine |
| `ms_dataflow/ids.py` | every hash (shared by the Planner and Resolvers) |
| `ms_dataflow/registry/` | `ast` analysis, ownership |
| `ms_dataflow/config/` | loading and validating DAG, IAM, resolvers |
| `ms_dataflow/planner.py` | a pure function; never writes to the DB |
| `ms_dataflow/execute/engine.py` | queue, result registration, retries, failure propagation (single thread) |
| `ms_dataflow/execute/scheduler.py`, `worker.py` | both sides of the HTTP server |
| `ms_dataflow/execute/local.py` | `LocalRunner`, runs everything in one process (for tests) |
| `ms_dataflow/ops.py` | deletion, hot/cold retention, lineage lookup |
| `ms_dataflow/ui/` | the JSON API the web UI reads, and serving the build output |
| `ms_dataflow/metrics.py`, `dag_store.py` | aggregation and log queries for the UI, DAG validation and saving for the editor |
| `frontend/` | web UI source (Vue 3 + Vue Flow). [frontend/README.en.md](frontend/README.en.md) |
| `tests/fixtures/calc/` | domain-free services for verification. Framework tests use these |

Tests verify only framework behaviour, using the minimal services in `tests/fixtures/calc`. `examples/` is for users, and
`tests/test_examples.py` only checks that the example still works.

## What tests must protect first

If any of these five break, wrong data goes out silently. When you touch related code, check the tests too.

1. **Hash determinism** — the same input always gives the same `lineage_key` and `artifact_id`
2. **Planner and Resolver ID agreement** — `planned_id` must equal the ID the Resolver issues
3. **Version normalization** — differences only in comments or whitespace give the same version; different logic gives a different version
4. **Ownership** — an Action reachable from two services is a load error
5. **Restart safety** — killing a Worker mid-run gets the step reassigned (`tests/test_distributed.py`).
   There is no test yet that kills the Scheduler itself at an arbitrary point and restarts it.

## Code style

```bash
uv run ruff check . --fix
uv run ruff format .
uv run mypy ms_dataflow
```

## Design principles (review criteria)

- If `artifact_id`, `lineage_key`, queues, leases, HTTP or serialization formats leak into user code, the abstraction is broken.
- Do not let things blow up at runtime; stop them at load time. Error messages carry all five: file, line, declaration source, reason, how to fix.
- Each layer has exactly one responsibility for data.
- When in doubt, come back to this sentence: **a layer that makes permissions, failures and tracing easy for data moving between services — not a system that manages whole services.**

## License

Contributed code is distributed under MIT.

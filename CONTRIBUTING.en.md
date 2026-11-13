# Contributing

[한국어](CONTRIBUTING.md) | **English**

Current version: **0.5.1.** What comes next is listed under "What comes next" in [docs/en/roadmap.md](docs/en/roadmap.md).

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

## What CI checks

When you open a pull request, GitHub Actions checks five things. The name of the failed job tells you what kind of problem it is.

| job | What it checks | If it fails |
| --- | --- | --- |
| 1. lint | `ruff check`, `ruff format --check`, `mypy` (strict) | run the commands under "Code style" |
| 2. guards | MSDF's philosophy, architecture, compatibility and docs (`tests/guards/`) | follow the failure message's `[원칙] [이유] [고칠 방법]` (principle, reason, how to fix) |
| 3. test | every feature, on Python 3.11, 3.12 and 3.13 | run that test locally with `uv run pytest -k name` |
| 4. e2e | "Getting started" end to end, as a user: `msdf init` → `check` → `up --token` → services → `invalidate` | `uv run pytest tests/e2e -v` |
| 5. install | an install without extras (does `msdf check` work?), and a wheel that includes the UI | check whether a core module imports a server library |

Principles the guards check:

| Area | Principles |
| --- | --- |
| Philosophy | Eight public functions (`service`, `action`, `order`, `start`, `context`, `delete`, `invalidate`, `cancel`). Service code does not import engine internals, and services do not import each other. Responses and deliveries the engine gives a service never contain another service's name, exception text or DAG path. No scheduler, deployment or LLM-framework dependencies. `meta` never enters the cache key |
| Architecture | Core modules (decorators, registry, config, Planner) work without the server. The Planner is a pure function. Only the engine writes the metadata DB. Hashes live only in `ids.py`. Library code does not `print`. New fields in engine↔service messages have defaults |
| Compatibility | Cache keys and Action versions are the same for the same input, regardless of MSDF version or Python version. Changing `schema.sql` comes with a `SCHEMA_VERSION` bump and a migration. The version number agrees in three places, and CHANGELOG (ko/en) has an entry for it |
| Docs | Korean and English docs exist in pairs with the same number of headings, code blocks and tables. Every public function and `msdf` command is documented. Relative links are not broken. Python examples are valid syntax |
| Repository | No build output (`ui/dist`), local state (`.msdf`), `design/`, secrets or `breakpoint()` committed |

Guards can be changed on purpose. If your contribution changes a principle itself, agree on it in an issue first, and update the guard, the docs (ko/en) and the CHANGELOG in the same PR.

```bash
uv run pytest tests/guards -v     # guards only
uv run pytest                     # everything (including e2e, about 30 seconds)
```

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

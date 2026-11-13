# Roadmap

[한국어](../roadmap.md) | **English**

## Current status: 0.5.1

Runs on one machine as an engine (`msdf up`) plus several service processes.

| Step | Contents | Status |
| --- | --- | --- |
| 1 | ID computation and metadata tables (SQLite) | done |
| 2 | `@service`, `@action` decorators and version computation (AST normalization) | done |
| 3 | Code analysis (Action collection, ownership), DAG loader, load-time validation | done |
| 4 | Planner (only needed steps, cache exclusion, joining in-flight steps) | done |
| 5 | Local Resolvers (file, SQLite) and `resolvers.yaml` | done |
| 6 | Scheduler and service receiver: leases, heartbeats, retries, delivery | done |
| 7 | `msdf up`, `msdf check` | done |
| 8 | IAM rule checks (`order`, `flow`, `delete`), `@context` | done |
| 9 | Delete requests and retention policy (hot/cold) | done |
| 10 | Web UI (Vue): live map, DAG editor, logs | done |
| 11 | Declaring a service without a function, `service("name")` | done (0.2) |
| 12 | Versions include the project helper code an Action calls | done (0.2) |
| 13 | Token authentication for engine, services and UI (`--token`, `MSDF_TOKEN`) | done (0.2) |
| 14 | Live UI updates (SSE), IAM editing page, run cancellation | done (0.2) |
| 15 | Automatic DB migration, code analysis cache, `msdf init/status/runs/cancel` | done (0.2) |
| 16 | Request correlation: `request_id`, `meta`, `idempotency_key`, `error` for `on_fail` | done (0.3) |
| 17 | Data change step 1: `invalidate()`, `data_version`, `msdf invalidate` | done (0.3) |
| 18 | Contribution CI: philosophy, architecture, compatibility and docs guards, e2e, install checks | done (0.3.1) |
| 19 | Data change step 2: `subscribe`, `cancel(request_id)`, subscriptions page | done (0.4) |
| 20 | Slot type check at load time, ending idle subscriptions | done (0.5) |
| 21 | Removing a 40ms wait between steps, performance measurements | done (0.5.1) |

## Direction

One sentence sums up what MSDF tries to keep:

> **A layer that makes permissions, failures and tracing easy for data moving between services — not a system that manages whole services.**

The principles that follow from it:

- **Less to memorize.** Eight functions and three YAML files should be everything. If data IDs, queues, HTTP or serialization formats show up in user code, the design is rolled back.
- **Stop mistakes before running.** Rather than failing at runtime, report at load time with file, line, source, reason and how to fix.
- **Each part has one responsibility.** Data: Resolver. Provenance: Artifact table. Permissions: IAM. Order: Planner.
- **Usable locally first.** For now: one machine, SQLite. Spreading over several machines comes after.

## What comes next

With data change (`invalidate`, `subscribe`), the starting point — "react to data change" — is in place. Next come interactive speed and developer experience.

| Item | Contents |
| --- | --- |
| English messages and UI | CLI output, error messages and the web UI are in Korean today |
| Large data and streaming | `ctx.load()`, `ctx.save()` for reading and writing storage directly inside an Action |
| Force-stopping a running step, isolating user Actions | an option to run Actions in a subprocess |
| Trace export | lineage and step timings to OpenTelemetry |
| PyPI release, built-in PostgreSQL and S3 Resolvers | local first, then these |
| Multiple users and roles | today there is one token for the whole engine |

Not planned: periodic runs (cron), deploying or scaling services, LLM-specific features, code inside DAGs.
Measured and declined: reusing memory between consecutive steps in the same service ([How it works › Performance](how-it-works.md#performance)).

## Known limitations

- The version hash covers the Action body and the project code it calls. Changes in installed packages and functions picked dynamically
  (`getattr` etc.) are not tracked; bump `version=` yourself in those cases.
- Actions in modules loaded by dynamic import (`importlib.import_module`) are not collected (a warning is shown).
- If a user Action kills its service process, the step is re-run on another instance after the lease expires.
- On Windows with Python 3.12 or earlier, an editable install in a folder whose path contains non-ASCII characters (such as Korean) fails at startup.
  See [Installation › Troubleshooting](installation.md#troubleshooting).

## Contributing

See [CONTRIBUTING.en.md](../../CONTRIBUTING.en.md).

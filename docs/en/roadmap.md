# Roadmap

[한국어](../roadmap.md) | **English**

## Current status: 0.2.0

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

## Direction

One sentence sums up what MSDF tries to keep:

> **A layer that makes permissions, failures and tracing easy for data moving between services — not a system that manages whole services.**

The principles that follow from it:

- **Less to memorize.** Seven functions and three YAML files should be everything. If data IDs, queues, HTTP or serialization formats show up in user code, the design is rolled back.
- **Stop mistakes before running.** Rather than failing at runtime, report at load time with file, line, source, reason and how to fix.
- **Each part has one responsibility.** Data: Resolver. Provenance: Artifact table. Permissions: IAM. Order: Planner.
- **Usable locally first.** For now: one machine, SQLite. Spreading over several machines comes after.

## What comes next

| Item | Contents |
| --- | --- |
| English messages and UI | CLI output, error messages and the web UI are in Korean today |
| Large data and streaming | `ctx.load()`, `ctx.save()` for reading and writing storage directly inside an Action |
| Reusing memory between consecutive steps in the same service | skip re-reading an output that was just saved. Decide after measuring |
| Isolating user Actions | an option to run Actions in a subprocess |
| Force-stopping a running step | today a step already running in a service runs to the end after cancellation (its result is discarded) |
| Cancelling from service code | a `cancel()` that cancels an in-flight request by the key `order()` returned |
| PyPI release | today install from the repository or a git URL ([Installation](installation.md)). A release will ship the UI build in the wheel together with license notices |
| Built-in PostgreSQL Resolver | can be plugged in today through an entry point |
| Multiple users and roles | today there is one token for the whole engine |

## Known limitations

- The version hash covers the Action body and the project code it calls. Changes in installed packages and functions picked dynamically
  (`getattr` etc.) are not tracked; bump `version=` yourself in those cases.
- Actions in modules loaded by dynamic import (`importlib.import_module`) are not collected (a warning is shown).
- If a user Action kills its service process, the step is re-run on another instance after the lease expires.
- On Windows with Python 3.12 or earlier, an editable install in a folder whose path contains non-ASCII characters (such as Korean) fails at startup.
  See [Installation › Troubleshooting](installation.md#troubleshooting).

## Contributing

See [CONTRIBUTING.en.md](../../CONTRIBUTING.en.md).

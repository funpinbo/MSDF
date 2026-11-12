# How it works

[한국어](../how-it-works.md) | **English**

You do not need this to use MSDF, but it helps when you want to understand performance or failure behaviour.

## Processes

MSDF is a **library**, not a server you upload code to. There are two kinds of processes.

```text
          msdf up (engine process)
   ┌──────────────────────────────┐
   │  Scheduler + Planner + IAM   │
   │  SQLite (metadata)           │
   │  web UI (/ui)                │
   └──┬────────────┬──────────┬───┘
      │            │          │        HTTP both ways
  ┌───┴────┐  ┌────┴─────┐  ┌─┴──────┐
  │  app   │  │  source  │  │transform│   services you run as usual
  │+start()│  │ +start() │  │+start() │   = that service's Worker
  └────────┘  └──────────┘  └─────────┘
```

- **Engine** (`msdf up`): holds the configuration, receives requests, plans them and hands steps to services. It does not start services or import user code; it only reads the code with `ast`.
- **Service processes**: run by you. `start()` brings up a small receiver server that executes the steps the engine sends.
- **Data never passes through the engine.** Service processes read and write storage directly. The engine handles only metadata such as "where to put it" and IDs.

### Communication

| Direction | Path | Contents |
| --- | --- | --- |
| service → engine | `POST /register`, `/heartbeat`, `/unregister` | startup, liveness, shutdown |
| service → engine | `POST /order`, `/delete` | requests. The requesting service is verified against its registration |
| engine → service | `POST /run` | run a step. The service answers 202 immediately and runs it in the background |
| service → engine | `POST /step/result` | the step result. If reporting fails, the service sends it again |

## Engine components

| Component | Responsibility |
| --- | --- |
| Registry | collects services and Actions with `ast` analysis and decides ownership |
| IAM | decides whether a request and the DAG's flows satisfy the rules |
| Planner | walks back from the DAG's result and picks only the steps to run. A pure function that never writes to the DB |
| Artifact table | keeps metadata per piece of data: origin, creation time, checksum. Holds no actual data |
| Scheduler | queues steps and sends them to idle service instances. Leases, retries, failure propagation |
| Resolver | stores, reads and deletes data according to configuration. Runs inside service processes and is the only part that knows the storage type |

## Two IDs

| | Identity of the request (`lineage_key`) | Identity of the data (`artifact_id`) |
| --- | --- | --- |
| Created | **before** computing | right **after** storing (the Planner computes the same value in advance) |
| Inputs | service, Action, version, output slot, data ID per input slot, (for the first step) params | parent data IDs, the request identity, the generation |
| Used for | cache lookups, duplicate prevention, the return value of `order()` | locating data, tracing provenance |

The data ID is computed deterministically, so the Planner knows it before execution and the storage produces the same value when saving.
If the two differ, the engine fails that step (so that a wrong cache entry is never served).

## How one step runs

```text
Scheduler ── /run ──▶ service process
  1. read the input data from storage and pass it as the Action's arguments
  2. run the Action (sync functions in a separate thread, async functions on an event loop)
  3. store the return value per output slot and get data IDs back
  4. report the result to the engine → the engine registers the metadata and sends the next step
```

- One service process runs **one step at a time.** To increase throughput, run more instances of the same service.
- Services send heartbeats periodically, and the engine extends the leases of their steps meanwhile.

### Step states

```text
queued → leased → running → saved → done
                     │
                     └──▶ failed ──▶ (dependent steps) cancelled
```

## Failure handling

| Situation | Behaviour |
| --- | --- |
| An Action raises | retried up to `retries` times. Delay is `retry_delay × 2^(attempt-1)` |
| A service process dies | when heartbeats stop, the instance is removed and its step goes back to the queue for another instance (the retry count is not increased) |
| A step cannot be sent | the instance is removed and the step goes back to the queue |
| Retries exhausted | the step is `failed`, dependent steps `cancelled`. That run's `on_fail` gets `"failed"`; other runs that had joined the step get `"cancelled"` |
| Input data disappeared from storage | the data is marked "lost" and the run is re-planned (up to 3 times) |
| Several services request the same result at once | computed once, delivered once per request |
| The engine restarts | step states are in the DB, so work continues once services register again |

## Retention

- The latest N generations of the same request (`--keep-generations`) and the latest M results that differ only by version at the same position
  (same parents, same service.action.slot; `--keep-versions`) are kept **hot** and used as the cache.
- Older metadata moves, together with its descendants, to **cold** (`.msdf/cold.db`) and is kept for tracing only. Cache lookups use hot only.
- The data itself is never moved or deleted. How long it is kept is your storage's policy.
- Parent–child links are not moved, so lineage can be followed across hot and cold.

## Deletion

Data never changes, so the only way to get rid of it is a `delete()` request.

1. The IAM `delete` rules are checked.
2. The engine **records a deletion marker first.** From that moment the data is no longer used as cache.
3. The data is deleted from storage. If that fails, the marker stays and deletion is retried periodically.

By default descendants are kept and show up in tracing as "parent deleted". With `cascade=True`, descendants are deleted too.

## The engine's storage

The engine keeps metadata in a SQLite file (`.msdf/msdf.db`).

- **Only one dedicated engine thread writes to the DB.** Services do not read the queue themselves; the engine pushes work to them, so SQLite's concurrent-write problems do not arise.
- WAL mode lets the UI read state while the engine writes.
- During 0.x, if the DB structure changes between versions it is not migrated automatically; you are told to delete `.msdf/msdf.db`.
  That file holds only the cache and run history, so the actual data in your storage is unaffected.

## Performance

Most of a step's cost is **reading and writing data** plus the Action's own computation. The engine's planning and queueing take milliseconds.

- Data does not pass through the engine.
- DataFrames are stored as Parquet (columnar, small and fast).
- On a cache hit, the step is skipped without even reading the data.
- Queue, start, save and finish times are recorded per step, so the UI timeline shows where time goes.

## Web UI

Served with `msdf up` at `http://127.0.0.1:8787/ui`. It is a Vue app, and only its source (`frontend/`) is distributed, so it has to be built once
([README](../../README.en.md#building-the-web-ui)). The UI text is currently in Korean.

| Page | Contents |
| --- | --- |
| Live map | All registered Actions, grouped by service, on one graph. Each node shows done, failed, cached and running counts, success rate and average time; each edge shows how much data moved. Refreshed every 2 seconds; running flows are animated. Summary cards at the top: run success rate, failed steps, cache hit rate and more |
| DAG editor | Drag an Action from the list onto the canvas to create a node, and drag from an output dot to an input dot to connect. Pick the result slot with ☆, and set node options and deliveries in the right panel. The engine validates every change; saving writes `dags/<order>.yaml` and applies it to the engine immediately. Node positions are kept in the YAML's `layout` |
| Logs | Tabs for runs, steps, services, DAGs and the engine log. Filter by service, DAG, status and search text; click a step to see the error text and the lineage of its input and output data |
| Run detail | One run's DAG graph (with cache, joined and failed marks), step timeline, failure location and the lineage of the result data |

The same information is available as a JSON API.

| Path | Contents |
| --- | --- |
| `GET /api/overview?window=seconds` | every number on the map (per Action, per edge, per DAG, throughput) |
| `GET /api/catalog` | services, Action specs, instances |
| `GET /api/dags`, `/api/dags/{order}` | DAGs (nodes, edges and YAML for the editor) |
| `POST /api/dags/validate`, `PUT /api/dags/{order}`, `DELETE /api/dags/{order}` | validate, save, delete a DAG |
| `GET /api/runs`, `/api/runs/{run_id}` | run list and detail |
| `GET /api/steps` | step log (filter by service, order, status, run_id, q) |
| `GET /api/events` | engine log (latest 3000 lines) |
| `GET /api/artifacts/{artifact_id}` | data lineage (both hot and cold) |

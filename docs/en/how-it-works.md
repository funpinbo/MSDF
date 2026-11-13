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

## Three IDs

| | `request_id` | `lineage_key` | `artifact_id` |
| --- | --- | --- | --- |
| Identity of | one request (run) | the computation (same computation, same key) | one stored piece of data |
| Created | when `order()` is accepted | **before** computing | right **after** storing (the Planner computes the same value in advance) |
| Inputs | random (differs per request) | service, Action, version, output slot, data ID per input slot, (for the first step) params | parent data IDs, lineage_key, the generation |
| Used for | return value of `order()`, finding the request in deliveries, holding `meta` and `idempotency_key` | cache lookups, duplicate prevention (join) | locating data, tracing provenance |

When two users ask the same question, the `lineage_key` is the same (computed once) and the `request_id`s differ (delivered to each).

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
| A subscribed request's source is `invalidate()`d | a refresh run recomputes from the changed step. If the result equals the last delivery, the delivery step is `skipped` and nothing is sent. If permission was lost, the subscription ends and `on_fail` gets `"cancelled"` |
| Someone cancels a run (UI, `msdf cancel`) | steps used only by that run are stopped as `cancelled` and `on_fail` gets `"cancelled"`. Steps other runs have joined keep running. A step already running in a service finishes, but its result is discarded. The run's status is `cancelled` |

## Retention

- The latest N generations of the same request (`--keep-generations`) and the latest M results that differ only by version at the same position
  (same parents, same service.action.slot; `--keep-versions`) are kept **hot** and used as the cache.
- Older metadata moves, together with its descendants, to **cold** (`.msdf/cold.db`) and is kept for tracing only. Cache lookups use hot only.
- The data itself is never moved or deleted. How long it is kept is your storage's policy.
- Parent–child links are not moved, so lineage can be followed across hot and cold.
- **Run history** (runs and their steps) is kept separately from the cache, for `--keep-history` (default 7 days). The engine periodically removes
  older finished runs, 1,000 at a time. Unfinished runs and runs of live subscriptions are kept, and the cache and lineage are untouched,
  so the same request still hits the cache after its run is removed.

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
- When a new MSDF version changes the DB structure, the DB is **migrated automatically** at startup, after a backup `msdf.db.v<old version>.bak`
  is written. A DB created by a newer MSDF is refused. That file holds only the cache and run history, so deleting it leaves the actual data in your storage unaffected.
- Code analysis results are kept per file in `.msdf/scan.cache`, so unchanged files are not re-read (`--no-cache` turns it off).

## Performance

Most of a step's cost is **reading and writing data** plus the Action's own computation. The engine's planning and queueing take milliseconds.

- Data does not pass through the engine.
- DataFrames are stored as Parquet (columnar, small and fast).
- On a cache hit, the step is skipped without even reading the data.
- Queue, start, save and finish times are recorded per step, so the UI timeline shows where time goes.

Measurements (one machine, a 3-step chain within one service, file storage):

| Data between steps | Request → delivery | Engine dispatch between steps | Save + load (per step) |
| --- | --- | --- | --- |
| small dict to 0.1MB | about 27ms | about 2ms | under 1ms |
| 1.3MB (JSON, 10k rows) | about 65ms | about 2ms | about 23ms |
| 12.8MB (JSON, 100k rows) | about 375ms | about 2ms | about 165ms |

- With small data, the Action's own time dominates; the engine adds a few ms per step.
- With large data, saving and loading grow. For tabular data, pass DataFrames: the same 1M rows are 12.8MB with ~78ms load as JSON (a list),
  and 4.3MB with ~51ms load as a DataFrame (Parquet).
- "Let the next step in the same service use the just-saved output from memory" was measured and declined. With small data it would save under 3%;
  for large data it would require routing the next step to the same instance and holding data in memory, which complicates failure recovery.

### Under load

When many requests arrive, the engine's single DB thread sets the throughput ceiling. 0.6 cut the work that thread does.

- Picking runnable steps no longer reads the whole queue. Each step keeps a count of unfinished upstream steps (`waiting`), decreased as each one finishes.
  Only steps with `waiting` 0 are looked up, through an index, and only as many per service as it has idle instances.
- Leasing a step and marking it running are written in one transaction.
- Subscription handling is skipped at once when no subscription is live.
- Old run history is removed (`--keep-history`), so the DB does not grow forever.

Measurements (one machine, 500 requests × 3 steps, 4 service instances, 4 rounds):

| | 0.5.1 | 0.6.0 |
| --- | --- | --- |
| Throughput (runs/s) | 30.4 · 29.2 · 27.8 · 26.6 | 38.3 · 38.0 · 35.1 · 35.6 |
| Picking runnable steps (median) | 9.5ms | 1.0ms |
| Run and step records (200 a day, kept 3 days) | grow forever | stop at 800 and 3,200 |

## Web UI

Served with `msdf up` at `http://127.0.0.1:8787/ui`. It is a Vue app, and only its source (`frontend/`) is distributed, so it has to be built once
([README](../../README.en.md#building-the-web-ui)). The UI text is currently in Korean.

| Page | Contents |
| --- | --- |
| Live map | All registered Actions, grouped by service, on one graph. Each node shows done, failed, cached and running counts, success rate and average time; each edge shows how much data moved. Refreshed live; running flows are animated. Summary cards at the top: run success rate, failed steps, cache hit rate and more |
| DAG editor | Drag an Action from the list onto the canvas to create a node, and drag from an output dot to an input dot to connect. Pick the result slot with ☆, and set node options and deliveries in the right panel. The engine validates every change; saving writes `dags/<order>.yaml` and applies it to the engine immediately. Node positions are kept in the YAML's `layout` |
| Logs | Tabs for runs, steps, services, DAGs and the engine log. Filter by service, DAG, status and search text; click a step to see the error text and the lineage of its input and output data |
| Run detail | One run's DAG graph (with cache, joined and failed marks), step timeline, failure location and the lineage of the result data. **Cancel run** while it is running |
| Permissions | Edit, validate and save IAM layers and rules as tables. Try a permission |
| Logs › Subscriptions | live and ended subscriptions, refresh counts, sources they depend on. Refresh marks and "end subscription" on the run detail page |

The pages re-read data only when the engine sends a change signal over `/api/stream` (Server-Sent Events). If the signal is lost they fall back
to reading every 2 seconds, and the indicator at the top changes from "실시간" (live) to "폴링" (polling).

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
| `POST /api/runs/{run_id}/cancel` | cancel a running run |
| `POST /api/invalidate` | announce a source data change `{"action": "service.action", "params": {...}, "data_version": "..."}` (available even with `--no-ui`) |
| `GET /api/iam`, `POST /api/iam/validate`, `PUT /api/iam`, `POST /api/iam/try` | read, validate, save IAM; try a permission |
| `GET /api/stream` | change signals (Server-Sent Events) |
| `GET /api/subscriptions` | subscriptions (status, refresh count, sources they depend on, expiry) |

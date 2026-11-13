# Changelog

[한국어](CHANGELOG.md) | **English**

## 0.3.0 (in progress)

### New

- **You can tell which request a result belongs to** (request correlation).
  - `order()` returns a **request_id**. A delivery Action that declares a `request_id` argument receives the same value.
  - `order(..., meta={...})`: a small value handed back with the result (e.g. `session_id`). It is not used for the cache key or IAM, so the same question is computed once and delivered to each user separately.
  - `order(..., idempotency_key="...")`: sending the same key again does not create a new run.
  - `on_fail` can receive `error` (the last line of the failure cause).
  - The web UI's run detail shows meta and idempotency_key.

- **`invalidate()`: announce that source data changed** (data change, step 1).
  - When the service that reads the data calls `invalidate("fetch", params={...}, data_version=...)`, that Action and its downstream steps are recomputed from the next request. `data_version` becomes part of the cache key, so downstream steps follow by themselves.
  - Only your own Actions can be named. Operators and webhooks use `msdf invalidate` or `POST /api/invalidate`.
  - Going back to an old `data_version` reuses the old cache. Actions never invalidated keep their cache.

### Changed

- **`order()` now returns a request_id instead of a lineage_key.** `delete()` accepts either.
- DB schema v4 (migrated automatically at startup, with a backup).

## 0.2.0 — 2026-11-12

### New

- **Declaring a service without a function**: one line, `service("search")`. A service that only provides Actions no longer needs an empty `def search(): ...`. The `@service` decorator still works.
- **Versions follow helper code**: when a function, class or module constant in your project that an Action uses changes (in the same file or an imported one), that Action gets a new version and is recomputed. Actions without helpers keep the same version as in 0.1.
- **Engine token**: `msdf up --token` (or `MSDF_TOKEN`). Services → engine, engine → services, the web UI and the CLI must all send the same token.
- **Cancelling runs**: from the run detail page in the web UI, `msdf cancel RUN_ID`, or `POST /api/runs/{id}/cancel`. The requesting service's `on_fail` receives `"cancelled"`; steps other requests are waiting on keep running. New run status `cancelled`.
- **Permissions page in the web UI**: edit, validate and save IAM layers and rules as tables (applied to the engine at once), plus "try a permission" without running anything.
- **Live web UI**: instead of polling every 2 seconds, pages re-read only when the engine sends a change signal over `/api/stream` (SSE). Falls back to polling if the stream drops.
- **Automatic DB migration**: an old-schema `.msdf/msdf.db` is migrated at startup, leaving a backup (`msdf.db.v<n>.bak`).
- **Code analysis cache**: unchanged files are not re-analysed (`.msdf/scan.cache`; turn off with `--no-cache`).
- **CLI**: `msdf init` (new project skeleton), `msdf status`, `msdf runs`, `msdf cancel`.

### Changed

- Actions that use helper functions get versions computed the new way, so their 0.1 cache is recomputed once.
- `@action` on a method inside a `class` is now a load error (it could previously be mistaken for a module-level function).
- Empty `...` bodies in the docs and examples were replaced with real code.

## 0.1.0

First public version. The engine (`msdf up`) and service processes, the Planner and cache, IAM, deletion and retention, the web UI (live map, DAG editor, logs).

# Changelog

[한국어](CHANGELOG.md) | **English**

## 0.4.0 — 2026-11-13

### New

- **Subscriptions (`subscribe`)**: `order(..., subscribe="30m")`. During that time, whenever a source the result depends on is `invalidate()`d, the engine recomputes from the changed step and delivers again **to the same delivery Action, with the original request_id and meta** (data change step 2).
  - The delivery Action's `refresh` argument (0, 1, 2, …) tells which round it is.
  - If the recomputed result equals the last delivery, it is not sent (the delivery step is `skipped`).
  - At most one refresh per subscription at a time, spaced by `--refresh-min-gap` (default 1s). A change during a refresh triggers one more.
  - IAM is re-checked on every refresh. If permission was lost, the subscription ends and `on_fail` gets `"cancelled"` with the reason.
  - Ends on expiry, `cancel()` or a DAG change. Live subscriptions are capped by `--max-subscriptions` (default 1000).
- **`cancel(request_id)`**: stop your own request or end its subscription from service code. There are now eight public functions.
- Web UI: Logs › Subscriptions tab, refresh marks and "end subscription" on the run detail page. API `GET /api/subscriptions`.
- Chatbot example: each conversation asks with `subscribe="10m"`, and `search.py` calls `invalidate()` when `sample_docs.json` changes. A new question `cancel()`s the previous question's subscription.

### Changed

- `on_fail`'s `error` now receives only **fixed reason sentences chosen by the engine** (five of them). Another service's exception text no longer passes through (0.3 passed its last line).
- Services cannot see other services: a rejected `order()`'s `PermissionDenied.blocked` holds only the service's own order rule, and `ServiceUnavailable` names no services. A service's `invalidate()` returns only the new version, and `cancel()` only whether it succeeded. Details are in the engine log and the web UI. A CI guard (`test_isolation.py`) checks this.
- DB schema v5 (`subscription` table, `run.subscription_id`, `run.refresh_no`). Migrated automatically at startup, with a backup.
- Engine↔service messages gained `OrderRequest.subscribe`, `StepTask.refresh` and `CancelRequest` (all with defaults, so 0.3 services still connect).

## 0.3.1 — 2026-11-13

### Fixed

- **Action versions differed between Python versions.** The same code produced different versions on 3.11, 3.12 and 3.13, so an engine and a service on different Pythons could be refused as "already registered with different code", and upgrading Python alone could invalidate the cache. Version hashes are now independent of the Python version.
  - In exchange, **every Action's version changes once, so existing caches are recomputed once.**
- `msdf up --no-ui` also dropped the JSON API, so `msdf status`, `runs` and `cancel` did not work. `--no-ui` now turns off only the web pages.

### For contributors

- CI is split into five jobs: lint, guards, test (3.11–3.13), e2e, install.
- `tests/guards/`: checks MSDF's philosophy, architecture, compatibility (cache keys, Action versions, DB schema), docs (ko/en pairs, links, example syntax) and repository hygiene. A failure tells you the principle, the reason and how to fix it.
- `tests/e2e/`: runs "Getting started" end to end as a user (`msdf init` → `up --token` → services → `invalidate`).
- A pull request template and "What CI checks" in CONTRIBUTING.

## 0.3.0 — 2026-11-13

### New

- **You can tell which request a result belongs to** (request correlation).
  - `order()` returns a **request_id**. A delivery Action that declares a `request_id` argument receives the same value.
  - `order(..., meta={...})`: a small value handed back with the result (e.g. `session_id`). It is not used for the cache key or IAM, so the same question is computed once and delivered to each user separately.
  - `order(..., idempotency_key="...")`: sending the same key again does not create a new run.
  - `on_fail` can receive `error` (the last line of the failure cause).
  - The web UI's run detail shows meta and idempotency_key.

- **`invalidate()`: announce that source data changed** (data change step 1; step 2, subscribe, comes in 0.4).
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

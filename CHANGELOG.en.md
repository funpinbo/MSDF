# Changelog

[한국어](CHANGELOG.md) | **English**

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

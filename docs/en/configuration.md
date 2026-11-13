# Configuration

[한국어](../configuration.md) | **English**

MSDF is configured with three kinds of YAML files. Each knows only its own part; these boundaries are what let services stay unaware of each other.

| File | Knows | Does not know |
| --- | --- | --- |
| Decorators in code | its own Actions' slots, params, version, retries, fresh\_for | who it connects to, where data is stored |
| DAG files (`dags/*.yaml`) | connections between slots, the result, delivery targets | permissions, storage |
| IAM file (`iam.yaml`) | layers and allow rules | which DAGs and data exist |
| `resolvers.yaml` | storage per slot | flow, permissions |

All three live only on the engine side, where `msdf up` runs. Service processes do not need them.

## DAG files

One file describes how to produce one result. Every `*.yaml` in the `dags/` folder is read.

```yaml
# dags/daily_stats.yaml
order: daily_stats                # the name services use with order()

nodes:                            # node name: {service, action, options}
  load:      {service: source,    action: load, fresh_for: 1h}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}

edges:                            # node.output_slot → node.input_slot
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}

result: summarize.stats           # the slot that becomes the order's result

deliveries:                       # who receives the result
  - requester: app
    on_success: app.on_stats
    on_fail:    app.on_stats_failed
```

| Key | Meaning |
| --- | --- |
| `order` | The contract name. The same name in two DAGs is an error |
| `nodes` | The steps. `fresh_for`, `retries`, `retry_delay` set here take precedence over the decorator (`version` cannot be set) |
| `edges` | Connect an output slot to an input slot. One edge per input slot |
| `result` | The slot returned to the requesting service |
| `deliveries` | `on_success` and `on_fail` Actions per requesting service. Both are required and must be Actions of the requesting service itself |
| `layout` | (optional) Node positions for the web UI editor, `{node: [x, y]}`. No effect on execution |

DAG files can be written by hand or built in the web UI's [DAG editor](how-it-works.md#web-ui). Saving in the editor writes a file in the same format
and applies it to the engine immediately (runs already in progress finish with the plan they already have).

- An `on_success` Action must have exactly one input slot (the result arrives in it).
- An `on_fail` Action must have one argument to receive the failure reason (`"failed"` / `"cancelled"`).
- The engine walks back from `result` and computes only the steps it needs. Branches that do not lead to `result` are not run.

## IAM file

You can also edit layers and rules as tables on the web UI's **Permissions** page. It validates on every change; saving writes an `iam.yaml`
in the same format and applies it to the engine at once (runs already accepted are not affected). **Try a permission** on the same page checks
"would this order from this service pass?" without running anything.

Decides who may make which request, and where data may flow. One per project.
**Without this file, no permission checks are done** (everything is allowed, and `msdf up` warns). With the file, the default is deny.

```yaml
# iam.yaml
layers:
  account: {kind: ordered, levels: [viewer, analyst, admin]}    # an ordered layer
  service: {kind: flat, members: [app, source, transform]}

rules:
  - {type: order, account: ">=analyst", service: app}
  - {type: flow, from: source.load,         to: transform.clean,     account: ">=analyst"}
  - {type: flow, from: transform.*,         to: transform.*,         account: ">=analyst"}
  - {type: flow, from: transform.summarize, to: app.on_stats,        account: any}
  - {type: delete, account: ">=admin", service: app, target: "transform.summarize.*"}
```

### Layers

- You decide which layers exist. `account` is just an example (`tenant`, `region`, anything).
- `ordered` layers have an order, like levels, so comparisons such as `">=analyst"`, `"<admin"`, `"==viewer"` work. `flat` layers are name lists and accept `*` patterns.
- Layer values are provided by the service through [`@context`](writing-services.md#context).
- The `service` layer always exists without being defined, and the engine fills in its value automatically (the requesting service).

### Rule types

| Type | Checks | Required keys |
| --- | --- | --- |
| `order` | whether this account/service may make the order | layer conditions |
| `flow` | whether data may flow from this Action to that Action | `from`, `to` (`service.action`, `*` allowed), **a condition for every layer except `service`** (`any` allows all values) |
| `delete` | whether this account/service may delete this data | `target` (`service.action.slot` pattern), layer conditions |

A condition of `any` (or `*`) passes even when no value is given. A list as a condition passes if any item matches.

### How checks work

- When an order arrives, **every connection in the DAG up to the result** and the `on_success` delivery connection are checked, including steps that will be skipped thanks to the cache.
- If any is blocked, the whole order is refused, and what was blocked is reported in `PermissionDenied.blocked` and in the UI.
- `on_fail` passes no data, so it is not checked.
- There is no inheritance such as "if you can see the source you can see what is derived from it". If you want that policy, put the same account condition on each rule.

## resolvers.yaml

Decides where data is stored, per `service.action.slot`. Service code does not know this file, so changing storage does not change code.
**Without the file**, all data is stored as files under `<project>/.msdf/store`.

```yaml
source.load.rows:        {backend: sqlite, path: ./data/raw.db, table: raw_rows}
transform.summarize.stats: {backend: file, path: ./data/stats}
default:                 {backend: file, path: ./data/store}    # used when nothing matches
```

| Backend | Options |
| --- | --- |
| `file` | `path`, `allow_pickle` |
| `sqlite` | `path`, `table`, `allow_pickle` |

- `path` is relative to the folder containing the configuration file.
- `${ENV_NAME}` in a value is replaced by the environment variable by the engine, so passwords need not be written in the file. An unset variable is a load error.
- When the engine sends a step, it includes only the configuration for the slots that step reads and writes. Services never receive other services' storage settings.
- The data itself moves only between services and storage; it never passes through the engine.

### Using your own backend

Another package can provide a backend. Register an entry point in that package's `pyproject.toml` and use it by name in `backend:`.

```toml
[project.entry-points."msdf.resolvers"]
duckdb = "msdf_duckdb:DuckDBResolver"
```

A backend class takes the configuration keys as keyword arguments and implements `save`, `load`, `locate`, `delete`, `exists` and `close`
(see `ms_dataflow.resolvers.base.Resolver`). If the same `(lineage_key, generation)` already exists, `save` must not write again and must return the same ID,
and the ID must be created with `ms_dataflow.ids.artifact_id` so it matches the ID the engine computed in advance. The built-in backends are registered the same way.

## What is checked at load time

When `msdf check` and `msdf up` read the files, they check the following and report every problem at once.

| Item | Result |
| --- | --- |
| The DAG has a cycle | error |
| An input slot is not connected | error |
| The DAG refers to an Action or slot that does not exist in code | error |
| The same `order` name is used by several DAGs | error |
| `result`, `on_success` or `on_fail` points to a missing Action or slot | error |
| A delivery has no `on_fail` | error |
| A DAG node overrides `version` | error |
| An Action that is not a first step declares `params` | error |
| An IAM `flow` rule is missing a layer condition, or uses an unknown layer or level | error |
| An Action is reachable from two services at once | error |
| A service referenced by a DAG is not in this project | error (warning with `--allow-external`, checked at registration) |
| An output slot is not connected anywhere | warning |
| An Action belongs to no service | warning |

Registration through `start()` is also checked. A service with the same name but different code is refused, and so is a service whose `@context`
keys do not cover the layers used by the IAM rules.

## The `msdf` command

```bash
msdf init  [DIR]                                   # a new project skeleton (three services, a DAG, iam.yaml)
msdf check [--root .] [--config DIR] [--allow-external] [--no-cache]
msdf up    [--root .] [--config DIR] [--allow-external] [--no-cache]
           [--host 127.0.0.1] [--port 8787] [--db PATH] [--token SECRET]
           [--lease-ttl 60] [--keep-generations 3] [--keep-versions 3] [--no-ui] [--ui-dist DIR]

# ask a running engine (--engine defaults to MSDF_SCHEDULER or http://127.0.0.1:8787, --token to MSDF_TOKEN)
msdf status [--engine URL] [--token SECRET]        # which services are connected, last hour summary
msdf runs   [--engine URL] [--token SECRET] [--limit 20] [--status running|done|failed|cancelled]
msdf cancel RUN_ID [--engine URL] [--token SECRET] # cancel a running run
msdf invalidate SERVICE.ACTION [--param k=v ...] [--data-version V] [--engine URL] [--token SECRET]
                                                   # announce that source data changed (webhooks, operators)
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--root` | `.` | folder to look for service code in |
| `--config` | `--root` | folder containing `dags/`, `iam.yaml`, `resolvers.yaml` |
| `--allow-external` | off | allow DAGs to refer to services from other repositories |
| `--db` | `<config>/.msdf/msdf.db` | the engine's metadata database |
| `--lease-ttl` | 60 | step lease time (seconds). Heartbeats every third of it |
| `--keep-generations` | 3 | how many latest generations of the same request to keep in the cache (hot) |
| `--keep-versions` | 3 | how many results that differ only by version to keep hot for the same position |
| `--no-ui` | off | do not serve the web UI |
| `--ui-dist` | `ui/dist` inside the package | a built web UI folder. Also settable with the `MSDF_UI_DIST` environment variable |
| `--token` | `MSDF_TOKEN` | engine token. When set, services, the web UI, `msdf status` and so on must all send the same value |
| `--no-cache` | off | do not use the code analysis cache (`<config>/.msdf/scan.cache`), which skips re-reading unchanged files |

Service-side environment variables: `MSDF_SCHEDULER` (engine address, default `http://127.0.0.1:8787`), `MSDF_TOKEN` (engine token).

### Engine token

By default the engine has no authentication and listens only on `127.0.0.1`. Use a token when you open it to other machines.

```bash
export MSDF_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
msdf up --host 0.0.0.0          # reads MSDF_TOKEN (or the --token value)
MSDF_TOKEN=... python source.py # services use the same value
```

- Requests from services to the engine and from the engine to services (step dispatch) both check `Authorization: Bearer <token>`.
- The web UI asks for the token the first time it opens and keeps it in that browser only. Only the static `/ui` files and `/health` are open without it.
- The token does not encrypt traffic. On an untrusted network, put the engine behind an HTTPS proxy or an SSH tunnel.
- `msdf up` warns if `--host` is anything other than `127.0.0.1` and no token is set.

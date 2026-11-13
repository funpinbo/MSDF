# Writing services

[한국어](../writing-services.md) | **English**

There are only eight things you use.

```python
from ms_dataflow import service, action, order, start, context, delete
```

| Name | What it does |
| --- | --- |
| `service(name)` / `@service(name)` | Declares a service |
| `@action(...)` | Marks a function that reads or writes data and declares its slots |
| `order(name, params, meta=...)` | Asks for a result by name and returns a request_id |
| `start()` | Attaches this process to the engine |
| `@context` | Marks a function that provides values for permission checks (account and so on) |
| `delete(request_id)` | Deletes data produced by an `order()` |
| `invalidate(action, params)` | Announces that the source data your Action reads has changed |
| `cancel(request_id)` | Stops a request this service made, or ends its subscription |

Your service code never contains other services' names, database types, storage locations or data IDs. If it does, something is being used the wrong way.

## `service()` / `@service`

There are two ways to declare a service; both mean the same thing.

```python
service("transform")       # one line at module level. For a service with no entry function (it only provides Actions)
```

```python
@service("app")            # if the service has a function that runs it, put the decorator on that function
def app(day: str):
    order("daily_stats", params={"day": day})
```

- One per file, at module level only. The name must be a string literal (the code is read, not executed).
- Starting from the file that declares it, every `@action` found **by following imports within the project** belongs to this service.
  You do not declare ownership on Actions.
- Imports inside functions are followed too. `if TYPE_CHECKING:` blocks are skipped, and dynamic imports such as `importlib.import_module`
  are not followed (a warning is shown).
- Installed third-party packages are not followed.
- An Action reachable from two services at once is a load error. See [shared logic](#when-several-services-use-the-same-logic) below.

## `@action`

```python
@action(
    inputs=["rows"],        # input slot names (must match the function's argument names)
    outputs=["clean"],      # output slot names. Default ["out"]
    params=[],              # names taken from the order's params (first-step Actions only)
    version=None,           # computed from the function source if omitted
    retries=0,              # how many times to retry on an exception
    retry_delay=0.0,        # delay between retries (seconds). Doubles on each attempt
    fresh_for=None,         # "30m", "1h", "1d", … Cached forever if omitted
)
def clean(rows):
    return [r for r in rows if r["value"] is not None]
```

With nothing to declare, the parentheses can be dropped.

```python
@action
def on_stats_failed(status: str):
    print("failed:", status)
```

- Only on module-level functions.
- Option values must be literals (`inputs=NAMES` with a variable does not work), because the code is read without being executed.

### Inputs and outputs

- The names in `inputs` and `params` **must match the function's argument names.** A mismatch is reported at load time.
- The engine reads the input data and passes it as arguments, then stores the return value in the output slots. The function does not touch the database itself.
- With several outputs, return a tuple in the order of `outputs`.

```python
@action(inputs=["rows"], outputs=["stats", "outliers"])
def summarize(rows) -> tuple[dict, list]:
    return stats, outliers
```

- `async def` works too.

### Data that can be stored

| Type | Stored as |
| --- | --- |
| `dict`, `list`, `tuple`, `str`, numbers, `bool`, `None` | JSON |
| `bytes` | as is |
| pandas `DataFrame` | Parquet (needs `msdf[dataframe]`) |
| anything else | rejected (`UnsupportedType`). Turn on `allow_pickle: true` in the backend configuration to use pickle |

### Version

- Without `version`, the version is derived from the function source. Changing the logic creates a new version, and computation restarts at that step.
- **Functions, classes and module constants in your project** that the Action uses are part of the version too, whether they are in the same file
  or imported with `from util import normalize` or `import util`, including whatever they call in turn. Changing one helper gives a new version
  only to the Actions that use it.
- Changes to comments, whitespace, line breaks, docstrings or decorator options keep the same version.
- Version changes of installed packages (pandas, …) are not tracked, and neither are functions picked dynamically (`getattr`, a function taken
  from a dict). In those cases bump it yourself, e.g. `version="2"`. If you give `version`, only that value is used.
- A DAG file cannot override `version`.

### Freshness

- `fresh_for` is mostly used on the first step that fetches external data. After the period passes, the data is fetched again.
- `fresh_for`, `retries` and `retry_delay` set on a DAG node take precedence over the decorator.

## `order()`

```python
request_id = order("daily_stats", params={"day": day})
request_id = order("daily_stats", params={"day": day}, meta={"session_id": sid}, idempotency_key=msg_id)
```

- **Returns immediately.** Carry on without waiting for the result.
- The result arrives at the Actions listed in the DAG's `deliveries` (`on_success` / `on_fail`).
- The return value is a **request_id**. It differs per request (even for the same data). It can also be passed to `delete()`.

| Argument | Meaning | Part of the cache key? |
| --- | --- | --- |
| `params` | **what** to compute. Must match the first-step Action's `params` | yes |
| `meta` | a small value to find **who** gets the result (e.g. `session_id`). The engine keeps it and hands it back to the delivery Action. JSON, up to 4 KB | no; not used by IAM either |
| `idempotency_key` | if the same service sends the same key again, nothing new runs and the first request_id is returned. For resending after a network error | – |
| `subscribe` | a duration such as `"30m"`: during it, whenever a source the result depends on is `invalidate()`d, recompute and deliver again. `True` means no expiry. See [Subscriptions](#subscriptions-subscribe) | – |

Because `meta` is not part of the cache key, when two users ask the same question it is **computed once and delivered separately, each with its own `meta`**.

### What delivery Actions receive

```python
@action(inputs=["stats"])
def on_stats(stats: dict, meta: dict, request_id: str):     # meta and request_id only if declared
    send_to_user(meta["session_id"], stats)

@action
def on_stats_failed(status: str, meta: dict, error: str | None):
    send_to_user(meta["session_id"], f"failed ({status})")
```

| Argument | on_success | on_fail | Value |
| --- | --- | --- | --- |
| result slot (first name in `inputs`) | ○ | – | the DAG's `result` |
| `status` (first argument) | – | ○ | `"failed"` or `"cancelled"` |
| `request_id` | ○ | ○ | the value `order()` returned |
| `meta` | ○ | ○ | the `meta` given to `order()` (`{}` if none) |
| `error` | – | ○ | a fixed reason sentence chosen by the engine (below). Never another service's exception text |
| `refresh` | ○ | ○ | subscriptions: `0` is the first delivery; `1`, `2`, … are re-deliveries after a source changed |

Arguments you do not declare are not passed, so existing delivery Actions keep working. Computing (produce) Actions never receive `meta`:
a value outside the cache key must not change a result.
- The requesting service's name is filled in automatically from the file that called `order()`. You do not pass it, and you cannot pretend to be another service.
- The names in `params` must exactly match the names the DAG's first-step Action declares with `params=[...]`. Values must be JSON-serializable.

`order()` only raises exceptions from the `OrderError` family.

| Exception | When |
| --- | --- |
| `PermissionDenied` | Blocked by an IAM rule. `.blocked` holds only this service's own order rule (paths between other services are not revealed) |
| `UnknownOrder` | No DAG with that name, or this service is not in the DAG's deliveries |
| `ServiceUnavailable` | A service needed to produce this result is not connected (which one is not revealed) |
| `ParamError` | params names are missing or extra |
| `OrderError` | anything else (cannot reach the engine, …) |

```python
from ms_dataflow.errors import OrderError, PermissionDenied

try:
    order("daily_stats", params={"day": day})
except PermissionDenied as e:
    print("permission denied:", e.blocked)
except OrderError as e:
    print("order failed:", e)
```

### What a service cannot see

Services do not know each other. So the responses and deliveries the engine gives a service **never contain another service's name, Actions,
exception text or DAG path.** Who failed and why, which service is down, which connection was blocked by permissions: operators see those in the
web UI and the engine log.

The `error` passed to `on_fail` is one of these five sentences (shown in Korean, as the engine emits them):

| When | `error` |
| --- | --- |
| this request's computation failed | 결과를 만드는 중 실패했습니다 |
| a computation shared with another request failed | 함께 기다리던 계산이 실패했습니다 |
| input data disappeared and could not be found even after re-planning | 입력 데이터를 찾지 못했습니다 |
| the request was cancelled (`cancel()`, UI, `msdf cancel`) | 요청이 취소되었습니다 |
| permission was lost while subscribed | 권한이 없어 구독을 끝냈습니다 |

For the same reason a service's `invalidate()` does not tell who depends on the data (not even how many subscriptions), and `cancel()` does not tell
which steps were shared with other requests. A CI guard (`tests/guards/test_isolation.py`) checks this principle.

## `start()`

```python
if __name__ == "__main__":
    start()      # attach to the engine (returns immediately)
    app.run()    # run your service as usual (a web server, …)
```

A service without its own main loop (one that only provides Actions) passes `block=True` so the process does not exit.

```python
if __name__ == "__main__":
    start(block=True)   # on Ctrl+C or SIGTERM, unregisters and exits
```

- Registers with the engine the services and Actions reachable by import from the calling file, starts a small server in the background to receive
  step requests, then **returns immediately**.
- The port is picked automatically. Run the same service several times and the engine hands work to whichever instance is idle.
- The engine address is taken from the argument → the `MSDF_SCHEDULER` environment variable → `http://127.0.0.1:8787`, in that order.
- If the engine was started with a token (`msdf up --token`), pass the same value with `token=` or the `MSDF_TOKEN` environment variable. A wrong one raises `RegistrationError`.
- If the engine is not up yet, it keeps retrying. With `start(required=False)` it only warns and keeps trying in the background. `timeout=` seconds limits the wait.
- If a service with the same name is already registered with **different code**, it raises `RegistrationError`. Stop the old process and start again.
- Unregisters when the process ends.

| Argument | Default | Meaning |
| --- | --- | --- |
| `scheduler` | `MSDF_SCHEDULER` or `http://127.0.0.1:8787` | engine address |
| `port` | `0` (automatic) | receiver server port |
| `required` | `True` | whether to wait when the engine is not up |
| `host` | `127.0.0.1` | receiver server address |
| `root` | folder of the calling file | project folder where code analysis starts |
| `timeout` | none | maximum time to wait for the engine (seconds) |
| `block` | `False` | if `True`, does not return and waits until Ctrl+C or SIGTERM. For services that only provide Actions |
| `token` | `MSDF_TOKEN` | engine token (same value as `msdf up --token`) |

## `@context`

If your IAM rules use layers such as account levels, add one function that provides those values.

```python
@context
def who() -> dict:
    return {"account": current_user.role}
```

- Called on every `order()`, because the logged-in user can differ per request.
- The returned keys must match the layer names in `iam.yaml`. If a layer used by the rules is missing, registration is refused at `start()`.
- The engine **trusts these values as given.** How they are obtained and verified is up to the service (your authentication system).
- Not needed if your only layer is the service.

## Subscriptions (subscribe)

Instead of receiving a result once, **receive it again when the data it depends on changes.** Use it to keep an answer fresh while, for example, a chat window is open.

```python
@service("chatbot")
def ask(session_id: str, q: str) -> str:
    return order("search_result", params={"q": q}, meta={"session_id": session_id}, subscribe="30m")

@action(inputs=["result"])
def on_search_result(result: str, meta: dict, refresh: int):
    send_to_user(meta["session_id"], result if refresh == 0 else f"(updated) {result}")
```

- For 30 minutes, whenever one of the sources the result depends on (search, documents, …) is `invalidate()`d, the engine **recomputes with the same
  params and meta and delivers to the same delivery Action.** The request_id is the original one, so the service needs no new bookkeeping; `refresh` tells which round it is.
- Only the changed step and its downstream steps are recomputed (the rest comes from the cache).
- **If the recomputed result is the same as last time, it is not delivered.** Users do not get the same answer twice.
- However many changes arrive, one subscription has at most one refresh at a time, spaced by a minimum gap (`msdf up --refresh-min-gap`, default 1s). A change during a refresh triggers one more afterwards.
- Every refresh is checked against IAM again. If permission was lost, the subscription ends and `on_fail` gets `status="cancelled"` with the reason (`error`).
- It ends on: expiry, `cancel(request_id)`, lost permission, or a DAG change that makes the same request impossible. `subscribe=True` (no expiry) is allowed within `msdf up --max-subscriptions` (default 1000).
- MSDF never checks sources itself. The only change signal is `invalidate()` from the service that reads the data.

## `cancel()`

```python
request_id = order("search_result", params={"q": q}, subscribe="30m")
# when the user changes the question or closes the chat window
cancel(request_id)
```

- Only requests made by this service can be cancelled.
- If it is running, it stops and `on_fail` gets `status="cancelled"`. Steps other requests are waiting on keep running.
- If it is a subscription, the subscription ends too. Ending only the subscription of an already finished request delivers nothing.
- Returns `True` if something was stopped or ended. Operators do the same with `msdf cancel REQUEST_ID` or from the run detail page in the web UI.

## `invalidate()`

**The service that reads the source data** (an external DB, a web page, a file) announces that it changed.

```python
service("search")

@action(params=["q"], outputs=["docs"])
def fetch(q: str) -> list: ...

# from a webhook, CDC, the service's own check, ...
invalidate("fetch", params={"q": "refund"})       # only what these params produced
invalidate("fetch")                                # everything fetch produced
invalidate("fetch", data_version="etag-42")        # give the new version yourself
```

- From the next request, that Action and **every downstream step that depends on its result are recomputed**: `data_version` is part of the
  cache key, so downstream input IDs change too. You do not need to know who depends on the data.
- Only **your own service's Actions** can be named. If another service's data changed, that service announces it.
- If you pass `data_version`, that value is the version; going back to an old value reuses the old cache. Without it the engine makes a new one.
- Steps already running are not touched.
- The cache key of an Action that was never invalidated does not change.
- Operators and external webhooks do the same with `msdf invalidate search.fetch --param q=refund` or `POST /api/invalidate`.
- MSDF never checks (polls) sources itself; the service that knows the data decides when it changed. If time is enough, use `fresh_for`.

## `delete()`

```python
request_id = order("daily_stats", params={"day": day})
# ... once you are done with the result
delete(request_id)                 # delete that result
delete(request_id, cascade=True)   # also delete data produced from it
```

- Checked against IAM `delete` rules. Raises `PermissionDenied` if blocked.
- The engine first records a deletion marker, so from that moment the data is no longer used as cache. If deleting the stored data fails,
  the marker stays and deletion is retried later.
- Returns the number of Artifacts deleted.

## When several services use the same logic

Put the logic in a plain module without `@action`, and give each service its own Action that calls it.

```python
# common/cleaning.py   (no @action; any service may import it)
def drop_empty(rows):
    return [r for r in rows if r["value"] is not None]

# transform.py
@action(inputs=["rows"], outputs=["clean"])
def clean(rows):
    return drop_empty(rows)

# report.py
@action(inputs=["rows"], outputs=["clean"])
def tidy(rows):
    return drop_empty(rows)
```

Even with the same logic, results from different services are stored separately. If several services need to share the result itself,
make it a separate service and request it with `order`.

## What load errors look like

Messages are in Korean. This one says: the declared input slot 'rows' is not a function argument; function arguments: data;
how to fix: rename clean's argument to 'rows' or fix the declaration.

```text
MSDF 로딩 오류: transform.py:12
  @action(inputs=["rows"])
  def clean(data):

  선언한 입력 슬롯 'rows'가 함수 인자에 없습니다.
  함수 인자: data
  고칠 방법: clean의 인자 이름을 'rows'로 맞추거나 선언을 고치세요.
```

When there are several errors, they are all collected and shown together instead of stopping at the first (`LoadErrors`).

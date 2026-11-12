# Writing services

[한국어](../writing-services.md) | **English**

There are only six things you use.

```python
from ms_dataflow import service, action, order, start, context, delete
```

| Name | What it does |
| --- | --- |
| `@service(name)` | Marks a service's entry point |
| `@action(...)` | Marks a function that reads or writes data and declares its slots |
| `order(name, params)` | Asks for a result by name |
| `start()` | Attaches this process to the engine |
| `@context` | Marks a function that provides values for permission checks (account and so on) |
| `delete(key)` | Deletes data produced by an `order()` |

Your service code never contains other services' names, database types, storage locations or data IDs. If it does, something is being used the wrong way.

## `@service`

```python
@service("app")
def app(day: str): ...
```

- Put it on the one function that runs the whole service. It must be a module-level function.
- Starting from the file that holds this function, every `@action` found **by following imports within the project** belongs to this service.
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
def clean(rows): ...
```

With nothing to declare, the parentheses can be dropped.

```python
@action
def on_stats_failed(status: str): ...
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
- Changes to comments, whitespace, line breaks, docstrings or decorator options keep the same version.
- Changes in **other functions** that the Action calls are not detected. In that case bump it yourself, e.g. `version="2"`.
- A DAG file cannot override `version`.

### Freshness

- `fresh_for` is mostly used on the first step that fetches external data. After the period passes, the data is fetched again.
- `fresh_for`, `retries` and `retry_delay` set on a DAG node take precedence over the decorator.

## `order()`

```python
key = order("daily_stats", params={"day": day})
```

- **Returns immediately.** Carry on without waiting for the result.
- The result arrives at the Actions listed in the DAG's `deliveries` (`on_success` / `on_fail`).
- The return value is the identity (key) of the request. The same request gives the same key. It can be passed to `delete()`.
- The requesting service's name is filled in automatically from the file that called `order()`. You do not pass it, and you cannot pretend to be another service.
- The names in `params` must exactly match the names the DAG's first-step Action declares with `params=[...]`. Values must be JSON-serializable.

`order()` only raises exceptions from the `OrderError` family.

| Exception | When |
| --- | --- |
| `PermissionDenied` | Blocked by an IAM rule. `.blocked` lists the blocked connections |
| `UnknownOrder` | No DAG with that name, or this service is not in the DAG's deliveries |
| `ServiceUnavailable` | A service on the DAG's path is not running. `.missing` lists them |
| `ParamError` | params names are missing or extra |
| `OrderError` | anything else (cannot reach the engine, …) |

```python
from ms_dataflow.errors import OrderError, PermissionDenied

try:
    order("daily_stats", params={"day": day})
except PermissionDenied as e:
    print("permission denied:", e.blocked)
except OrderError:
    ...
```

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

## `delete()`

```python
key = order("daily_stats", params={"day": day})
...
delete(key)                 # delete that result
delete(key, cascade=True)   # also delete data produced from it
```

- Checked against IAM `delete` rules. Raises `PermissionDenied` if blocked.
- The engine first records a deletion marker, so from that moment the data is no longer used as cache. If deleting the stored data fails,
  the marker stays and deletion is retried later.
- Returns the number of Artifacts deleted.

## When several services use the same logic

Put the logic in a plain module without `@action`, and give each service its own Action that calls it.

```python
# common/cleaning.py   (no @action; any service may import it)
def drop_empty(rows): ...

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

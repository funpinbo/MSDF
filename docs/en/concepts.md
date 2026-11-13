# Concepts

[한국어](../concepts.md) | **English**

## The problem MSDF solves

As microservices multiply, service A calls B, B reads C's database, and they all end up knowing about each other.
Changing one flow then means changing several services, and it becomes hard to trace where data came from, who may see it, and where it failed.

This problem first showed up in a chatbot. How a chatbot ends up conducting the whole flow as features are added is described in [Why MSDF](background.md).

MSDF manages the **data** moving between services in a single layer.

- A service only **asks for a result by name**.
- Who produces it, and in what order, is decided by the **DAG file**.
- Who may request and receive what is decided by the **IAM file**.
- Which storage the data goes into is decided by the **resolvers file**.

Where tools such as Airflow build flows around **tasks**, MSDF builds them around **data (Artifacts)**.

## What it does and does not do

MSDF is **a layer that makes permissions, failures and tracing easy for data moving between services.** It is not a system that manages whole services.

| Does | Does not |
| --- | --- |
| Compute only the steps needed for the requested result | Start or deploy services |
| Record each piece of data's origin (source, service, function, version) | Guarantee the same result for the same input (that is the service's job) |
| Check permissions in one place | Manage databases. It only sends save and delete requests; retention is up to your database |
| Re-run from the failed step | Manage context inside a service. When to check for a result is up to the service |

## Terms

| Term | Meaning |
| --- | --- |
| **Service** | A unit of functionality you write. Its entry point is marked with `@service`. |
| **Action** | A function in a service that reads or writes data. Marked with `@action`; it has input and output slots. |
| **Slot** | The name of an Action's input or output. It means something only inside that function. Slots are connected by the DAG. |
| **Param** | A value sent along with a request. The first-step Action receives it by name. It must be JSON-serializable. |
| **Order** | Asking for a result by name. You call `order("daily_stats", params=...)` and do not wait for the result. |
| **DAG** | A YAML file describing how to produce one result: steps, connections, the result slot, and where to deliver it. |
| **Artifact** | Data that is stored and crosses a service boundary. Once created, it never changes. |
| **Delivery** | Result notification. On success it wakes the `on_success` Action; on final failure, the `on_fail` Action. |
| **request_id** | The ID of one request. `order()` returns it and deliveries receive the same value. It differs per request even for the same data. |
| **meta** | A small value attached to a request and handed back with the result (e.g. a session_id). Not used for computing (not in the cache key). |
| **subscribe** | A request that does not end with one result: it receives the result again whenever the data it depends on changes. `order(..., subscribe="30m")`. |
| **data_version** | The version of source data. When the service that reads it changes it with `invalidate()`, computation restarts from that step. |

### What counts as an Artifact

Data becomes an Artifact at the point where a service cannot produce it itself and asks another service for it.
Values used and discarded inside one service, and external input such as user input, are not Artifacts. Every Artifact starts from an Order.

## How one request is processed

```text
1. order        app calls order("daily_stats", params={"day": ...}, meta=...) → gets a request_id and returns immediately
2. permissions  check the request itself and every connection in the DAG against the IAM rules. If any is blocked, the whole request is denied
3. cache        if a result for the same request already exists and has not expired, use it
4. plan         walk back from the result and pick only the steps that actually need computing
5. execute      each service process runs its steps one at a time and stores the results
6. deliver      wake app's on_success (or on_fail), with the request_id and meta
```

Your service code only provides the functions for steps 1 and 6. The engine handles the rest.

## Caching: the same request is not recomputed

MSDF assumes that **the same input and the same logic produce the same result.** So before computing, it decides "has this request been made before?".

What decides whether two requests are the same:

- which Action of which service
- the Action's version (a hash of the normalized function source; comments, whitespace, docstrings and decorator options do not affect it)
- which input data came in through which slot
- for the first step, the order's params
- the `data_version` of source data announced with `invalidate()` (none if never announced)

What is **not** used: the requesting account, `retries`, `fresh_for`. So a different account making the same request shares the result
(permissions are still checked separately).

| What changed | Result |
| --- | --- |
| The same day is requested again | All steps are skipped and the stored result is returned |
| The logic of `summarize` changed | `load` and `clean` results are reused; computation restarts at `summarize` |
| A different day is requested | Computed from scratch |
| `load`'s `fresh_for` has passed | Recomputed from `load` |
| The `source` service announced a change with `invalidate("load")` | Recomputed from `load` (downstream steps follow by themselves, since their inputs changed) |
| The same request arrives several times at once | Computed once, delivered once per request |

Making the same input produce the same output (idempotency) is the service's responsibility.

## Failure: restart from where it failed

Each step's result is stored, so a failure halfway does not mean starting over.

- If an Action raises, it is retried up to `retries` times.
- If a service process dies, its step is re-run on another instance (or on the restarted process).
- If it still fails after all retries, the step becomes `failed`, the steps that depended on it become `cancelled`, and the requesting service's `on_fail` is woken.
- `on_fail` receives only `"failed"` or `"cancelled"`. See the web UI for the detailed cause.
- If input data has disappeared from storage (deleted by your database's own policy), it is treated as a cache miss and re-planned.

## Data provenance

Every Artifact records "from which source data, by which function (and version) of which service it was produced".
From any result you can walk back through the data and code versions it passed through, and the same records serve as the cache and as restart points.

## Next

- Functions and options in detail → [Writing services](writing-services.md)
- What actually happens inside the engine → [How it works](how-it-works.md)

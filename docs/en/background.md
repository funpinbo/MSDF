# Why MSDF

[한국어](../background.md) | **English**

## Starting point: the chatbot ends up carrying everything

Most chatbots today are built as agents. They do not stop at answering questions; features such as search, document embedding, summarization,
external API calls and user lookups keep getting added.

The problem is how those features get added. Each new feature usually brings this into the chatbot code:

- which features to call, and in what order
- how to pass one feature's result to the next
- where to store results, and when to rebuild them
- where to restart if something fails halfway

Before long the chatbot becomes **the conductor (orchestrator) of all the logic**. Adding or removing a single feature means changing the chatbot,
and features start calling each other directly and become entangled. The bigger the chatbot gets, the harder it is to know what to change to affect what.

```text
Common today                                What we want

chatbot ─┬─▶ search                         chatbot ──"I need this result"──▶ MSDF
         ├─▶ embedding                                                       │
         ├─▶ summarize                       search ─▶ embedding ─▶ summarize ◀┘
         └─▶ (one more line per feature)     (the wiring lives only in the DAG file)
```

## A chatbot changes a lot of data

A chatbot changes data far more than most systems.

- Every question produces new search results and intermediate data.
- Source documents get updated; the embedding model or the summarization method changes.
- The same question is asked again, and several features rebuild nearly the same data.

So it has to react precisely to "what changed, and what needs to be recomputed". If each feature makes that call on its own, the same work gets
repeated, or a change is missed and stale results are used.

## So we decided this

**Take orchestration out of the features.** Each feature (service) does only its own job. Who connects to whom, and in what order, lives in one place: the DAG file.

**Services do not know each other.** A service asks for a result by name and does not know who produces it.
Adding or removing a feature leaves the other services' code untouched; only the DAG changes.

**Move on data changes.** The unit of flow is data (an Artifact), not a task. Because every piece of data records where it came from and which code
(version) produced it, only what changed is recomputed and unchanged results are reused.
When source data changes, the service that reads it only has to call `invalidate()`; the engine works out from lineage who depends on it.

**Give results back to exactly who asked.** So that answers never mix when many users ask at once, every request gets its `request_id` and
`meta` (e.g. a session_id) back with the result. The same question is still computed only once.

**Permissions, failures and tracing in one place.** However many features there are, "who may receive this data", "where did it fail" and
"where did this result come from" are answered in one place.

## Example: adding one feature

Say you want to translate the retrieved documents before summarizing them.

**Without MSDF** — you change the chatbot code.

```python
def answer(question):
    docs = search(question)
    docs = translate(docs)          # new: the chatbot has to know the order
    vectors = embed(docs)
    return summarize(vectors)
```

**With MSDF** — you write a translation service and add one node and its connections to the DAG. The chatbot code does not change.

```python
# translate.py — a new service; it declares only its own work
service("translate")

@action(inputs=["docs"], outputs=["out"])
def to_korean(docs):
    return [translate_text(d, target="ko") for d in docs]   # call whatever translation library you use
```

```yaml
# dags/search_result.yaml — the only place that changes
nodes:
  fetch:     {service: search,     action: fetch}
  translate: {service: translate,  action: to_korean}   # added
  embed:     {service: embedding,  action: embed}
  refine:    {service: processing, action: refine}

edges:
  - {from: fetch.out,     to: translate.docs}           # changed
  - {from: translate.out, to: embed.docs}               # added
  - {from: embed.out,     to: refine.vectors}
```

From the next request on, search results are reused from the cache and computation restarts at translation. To remove translation, delete the node
from the DAG. Dragging nodes in the web UI's DAG editor produces the same file.

## It started with a chatbot, but

The problem first showed up in a chatbot, but it is not unique to chatbots. Anywhere several services exchange data, features change often and
data is updated often, the same problem appears. In such places MSDF is the layer that handles **only the data moving between services**.
It does not start or deploy services, and it does not deal with the logic inside a service ([Concepts](concepts.md#what-it-does-and-does-not-do)).

## Next

- Run it yourself → [Getting started](getting-started.md)
- Terms and behaviour → [Concepts](concepts.md)

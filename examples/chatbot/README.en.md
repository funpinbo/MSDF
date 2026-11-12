# Chatbot example

[한국어](README.md) | **English**

Four services (chatbot, search, embedding, processing) exchange data without knowing about each other.
**No LLM or search engine is called.** It searches the sample documents in `sample_docs.json`, imitates vectors with word counts,
and uses the first sentence as the summary. The point is to show how MSDF wires the flow together.

The sample documents and questions are in Korean (refund policy, delivery, membership levels, password reset, exchanges).

```text
chatbot ──order("search_result", q)──▶ engine
search.fetch(q) ─▶ embedding.embed ─▶ processing.refine ─▶ chatbot.on_search_result
```

Run `uv sync --all-extras` at the repository root first, then run the commands below from this folder. If you installed with pip,
activate the virtual environment and drop `uv run`.

## Quick look in a single process

```bash
uv run python run_local.py "환불은 언제 되나요" "환불은 언제 되나요"
```

The second question ("When will I get a refund?" again) is the same request, so no step runs and the answer comes from the cache.
This demo runs its own engine inside its process, so **it does not show up in the web UI of `msdf up`.**

## Watch it in the web UI (two commands)

```bash
uv run msdf up                      # terminal 1 — engine. http://127.0.0.1:8787/ui
uv run python run_services.py       # terminal 2 — attaches the four services and sends a sample question every 3 seconds
```

Runs appear right away on the live map and in the logs. Ctrl+C stops all services. Change the interval with e.g. `ASK_EVERY=1`.

## Each service as its own process

```bash
uv run msdf up                  # terminal 1 — engine. See the flow at http://127.0.0.1:8787/ui
uv run python search.py         # terminal 2
uv run python embedding.py      # terminal 3
uv run python processing.py     # terminal 4
uv run python chatbot.py        # terminal 5 — type questions (an empty line exits)
```

The web UI appears only after it is built once at the repository root: `cd frontend && npm install && npm run build`.

## Files

| File | Contents |
| --- | --- |
| `chatbot.py` | the service that makes the order and receives the result. Provides the account level through `@context` |
| `search.py`, `embedding.py`, `processing.py` | one Action each |
| `dags/search_result.yaml` | the DAG connecting the four services |
| `iam.yaml` | permissions per account level |
| `resolvers.yaml` | search results in SQLite, everything else in files |
| `sample_docs.json` | sample documents |
| `run_local.py` | single-process demo (its own engine, no UI) |
| `run_services.py` | attaches the four services to a running engine and keeps sending questions (for the UI) |

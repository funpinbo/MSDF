# Installation

[한국어](../installation.md) | **English**

MSDF is **not on PyPI yet.** `pip install msdf` will not work; use one of the three methods below.

| Method | Where | Web UI |
| --- | --- | --- |
| [1. Install from the repository](#1-install-from-the-repository-recommended) | Where the engine (`msdf up`) runs, or where you try it first | Built inside the repository |
| [2. Install from a git URL](#2-install-from-a-git-url) | Each service project (other repositories) | Not needed (use `--ui-dist` if you run the engine there) |
| [3. Share a wheel file](#3-share-a-wheel-file) | Machines without internet or git access | Included in the wheel |

Requirements: Python 3.11 or later. Building the web UI needs Node.js 20.19 or later (22 recommended).

## Extras

With any method, pick only what you need with `[...]`.

| Extra | Contents | When |
| --- | --- | --- |
| (none) | decorators, models, static analysis, `msdf check` | writing and validating code |
| `runtime` | the above + the receiver server started by `start()` | actually running services |
| `server` | the above + Scheduler and web UI server | running `msdf up` |
| `dataframe` | pandas, pyarrow | exchanging DataFrames (stored as Parquet) |

The package name is `msdf`; the name you import in code is always `ms_dataflow`.

## 1. Install from the repository (recommended)

This is the simplest option where the engine runs and where you try MSDF first. The web UI builds right inside the repository.

With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/funpinbo/MSDF.git
cd MSDF
uv sync --all-extras
```

`uv sync` creates a virtual environment (`.venv`) inside the repository and installs the dependencies plus MSDF itself in **editable mode**.
It does not copy MSDF's code; it puts a single `.pth` file containing the repository path into `.venv`, so changes to the repository's code take effect
without reinstalling. From then on, `uv run ...` anywhere inside the repository uses this `.venv` (uv walks up to find `pyproject.toml`).

> Running `uv run` without `uv sync` also makes uv create `.venv` and install MSDF automatically, but **without the extras (`server`, `runtime`)**.
> `msdf check` then works, but `msdf up` and `start()` tell you an extra is missing. Run `uv sync --all-extras` once first.

With pip:

```bash
git clone https://github.com/funpinbo/MSDF.git
cd MSDF
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[server,dataframe]"
```

Build the web UI (once, and again whenever the UI source changes):

```bash
cd frontend
npm install
npm run build                      # output: ms_dataflow/ui/dist
```

Check:

```bash
msdf --version                     # with uv: uv run msdf --version
```

To update, run `git pull`, then `uv sync --all-extras` (or `pip install -e ".[server]"`) and `npm run build` again.

## 2. Install from a git URL

If your services live in their own repositories, install just the `runtime` extra from the git URL on the service side.

```bash
pip install "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git"
```

To pin a version, append a tag or commit.

```bash
pip install "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git@v0.2.0"
```

In a dependency file:

```text
# requirements.txt
msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git@v0.2.0
```

```toml
# pyproject.toml
[project]
dependencies = ["msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git@v0.2.0"]
```

With uv: `uv add "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git" --tag v0.2.0`.

**Installing from a git URL does not include the built web UI** (the repository does not contain build output). To run the engine and the UI
from such an install, clone the repository, build the UI once, and point to that folder.

```bash
msdf up --ui-dist /path/to/MSDF/ms_dataflow/ui/dist
# or with an environment variable: MSDF_UI_DIST=/path/to/MSDF/ms_dataflow/ui/dist msdf up
```

Running the engine without the UI is fine. `/ui` then shows how to build it, and the JSON API keeps working.

## 3. Share a wheel file

For servers without internet or git access, build a wheel file and copy it over. If you build the UI first, it goes into the wheel too.

```bash
cd MSDF
(cd frontend && npm install && npm run build)
uv build --wheel                   # or: pip install build && python -m build --wheel
ls dist/                           # msdf-0.2.0-py3-none-any.whl
```

On the target machine:

```bash
pip install "msdf-0.2.0-py3-none-any.whl[server]"
```

> The wheel contains the built code of the libraries the UI uses: Vue, vue-router, Vue Flow (which includes VueUse) and dagre are MIT;
> the d3 modules bundled inside Vue Flow (d3-zoom, d3-drag, …) are ISC. Both are permissive licenses with no restrictions on use, but
> if you distribute the wheel outside your organization, include each library's copyright notice and license text.

## What to install where

```text
engine machine        method 1 (server, build the UI)     msdf up
service A repository  method 2 (runtime)                  python service_a.py  ← start()
service B repository  method 2 (runtime)                  python service_b.py  ← start()
```

It is safest for the engine and all services to use **the same version**. Use the same tag in every git URL.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `pip install msdf` fails | It is not on PyPI yet. Use one of the methods above |
| On Windows, `msdf` or `python` fails at startup with `UnicodeDecodeError: 'cp949' codec can't decode` (or another code page) | The project path contains non-ASCII characters and Python is 3.12 or earlier, so the `.pth` file created by the editable install is read with the system code page. ① Turn on UTF-8 mode with `PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8 = "1"`; to keep it, `setx PYTHONUTF8 1` and open a new terminal), ② move the project to an ASCII-only path (e.g. `C:\dev\MSDF`) and recreate `.venv`, or ③ use Python 3.13 or later |
| `msdf up` says the server extra is needed, or `start()` says the runtime extra is needed | It was installed without extras. In the repository run `uv sync --all-extras`; with pip, `pip install -e ".[server]"` |
| `msdf: command not found` | Is the virtual environment active (`source .venv/bin/activate`)? With uv, use `uv run msdf` |
| `/ui` says the UI has not been built | `cd frontend && npm run build`, or `msdf up --ui-dist PATH` |
| `npm run build` fails with a Node version error | Node.js 20.19+ or 22.12+ |
| `http://127.0.0.1:8787/ui` does not open in the browser | ① Is `msdf up` running? (`run_local.py` has no web UI.) ② If the engine runs on a remote server or VM, `127.0.0.1` means that machine itself. Open a tunnel from your computer with `ssh -L 8787:127.0.0.1:8787 user@server`, then open `http://127.0.0.1:8787/ui`. On a trusted network you can also start `msdf up --host 0.0.0.0` and open `http://server-address:8787/ui` (allow port 8787 in the firewall). ③ If the page is blank, check that you ran `npm run build` in `frontend` |
| `start()` hangs while "waiting for the engine" | Is `msdf up` running, and is the address right (`MSDF_SCHEDULER`)? |
| The engine refuses to start because the DB was "created by a newer MSDF" | A `.msdf/msdf.db` made by a newer MSDF was opened by an older one. Match the versions, or delete the DB and restart (only the cache and run history are lost). Older DBs are migrated automatically at startup, leaving a `msdf.db.v<n>.bak` backup |
| A service stops with "the engine requires a token", or the web UI asks for a token | The engine was started with `--token` or `MSDF_TOKEN`. Give services the same `MSDF_TOKEN` and enter the same value in the UI |

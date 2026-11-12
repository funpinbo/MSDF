# MSDF web UI

[한국어](README.md) | **English**

The source of the screens `msdf up` serves at `/ui`. Vue 3 + Vue Flow + Vite. The UI text is currently in Korean.

The build output (`ms_dataflow/ui/dist`) is not committed. Build it once after cloning.

```bash
cd frontend
npm install
npm run build        # → ../ms_dataflow/ui/dist
```

Requires Node.js 20.19 or later (22 recommended). If you start `msdf up` without building, `/ui` shows these instructions. The engine and the JSON API work regardless of the build.

Where MSDF was installed from a git URL, the package contains no build output, so point to a built folder.

```bash
msdf up --ui-dist /path/to/MSDF/ms_dataflow/ui/dist   # or the MSDF_UI_DIST environment variable
```

## Development

```bash
msdf up              # terminal 1 — engine (8787)
npm run dev          # terminal 2 — http://localhost:5173/ui/ (/api is proxied to the engine)
```

## Screens

| Path | Page | Contents |
| --- | --- | --- |
| `#/` | Live map | All services, Actions and data flow on one graph. Done, failed, cached and running counts per Action, data moved per edge, success rate, throughput |
| `#/editor/:order` | DAG editor | Drag Actions to create nodes and drag from an output dot to an input dot to connect. Saving writes `dags/*.yaml` and applies it to the engine immediately |
| `#/logs/runs` | Run log | Filter by DAG, requesting service, status |
| `#/logs/steps` | Step log | Filter by service, DAG, status, search text. Error text and data lineage |
| `#/logs/services` | Services | Instances, heartbeats, per-Action statistics |
| `#/logs/dags` | DAGs | Per-DAG statistics and YAML |
| `#/logs/engine` | Engine log | The engine process's log, live |
| `#/runs/:id` | Run detail | One run's graph, step timeline, failure location, result lineage |

## Files

| File | Contents |
| --- | --- |
| `src/api.js` | API calls and periodic refresh (`usePoll`) |
| `src/layout.js` | automatic layout with dagre (grouped by service) |
| `src/pages/` | pages |
| `src/components/` | parts such as nodes, tables and charts |

## License

The code in this directory is MIT, like MSDF. The repository holds only the source; dependencies are downloaded by `npm install`.

Libraries that actually end up in the build output:

| Library | License |
| --- | --- |
| vue (@vue/runtime-dom, runtime-core, reactivity, shared) | MIT |
| vue-router | MIT |
| @vue-flow/core, background, controls, minimap (including @vueuse/core) | MIT |
| d3-zoom, d3-drag, d3-selection, d3-interpolate, … (bundled inside @vue-flow/core) | ISC |
| @dagrejs/dagre | MIT |

If you distribute the build output separately (for example inside a wheel), it contains the code above, so include each copyright notice and license text.
Build tools such as Vite do not end up in the output.

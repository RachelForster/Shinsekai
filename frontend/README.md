# Shinsekai React Frontend

This package is the React + TypeScript frontend rewrite defined by `../design.md`.
It keeps the existing Python/Qt business logic as the desktop/backend side and
accesses it only through `shared/platform`.

## Install Frontend Dependencies

```bash
cd frontend
pnpm install
```

## Start The React Settings Center

Use the launcher from the repository root:

| Platform | Command               |
| -------- | --------------------- |
| Windows  | `start-react.bat`     |
| macOS    | `start-react.command` |
| Linux    | `./start-react.sh`    |

The launcher runs `webui_react.py`, starts the Python bridge, serves
`frontend/dist`, and opens the settings UI in the default browser. If the build
is missing or older than the source tree, it runs `pnpm build` automatically as
long as `frontend/node_modules` is already installed.

## Sync App Version

Edit the repository root `VERSION` file first, then run:

```bash
cd frontend
pnpm sync:version
```

The script syncs the app version into `package.json`, Tauri `Cargo.toml`, the
`shinsekai-desktop` entry in `Cargo.lock`, `runtime_manifest.json`, and the
generated `src-tauri/resources/VERSION` file when it exists. Avoid global
search-and-replace so dependency versions are not changed accidentally.

## Required Checks

Run these before submitting React frontend changes:

```bash
cd frontend
pnpm format:check
pnpm lint:types
pnpm test
pnpm build
```

The React frontend CI runs the same formatting, type-checking, unit test, and
build commands for frontend changes.

## Visual Regression Tests

Visual regression tests cover the settings routes and the chat stage with
Playwright screenshots. Run them only when you need to inspect or update visual
baselines.

Terminal 1:

```bash
cd frontend
pnpm dev --host 127.0.0.1 --port 5174
```

Terminal 2:

```bash
cd frontend
pnpm exec playwright install chromium
pnpm test:visual
```

Use `pnpm test:visual:update` only when intentionally accepting a visual change.
The checked-in baselines live under `e2e/visual.spec.ts-snapshots/`; transient
`playwright-report/` and `test-results/` output is ignored.

## Development With Real Project Data

Terminal 1:

```bash
conda run -n shinsekai python frontend_bridge.py --host 127.0.0.1 --port 8787 --project-root .
```

Terminal 2:

```bash
cd frontend
VITE_SHINSEKAI_API_BASE=http://127.0.0.1:8787 pnpm dev
```

When starting the bridge from `frontend/`, use:

```bash
pnpm dev:bridge:conda -- --host 127.0.0.1 --port 8787
```

Without `VITE_SHINSEKAI_API_BASE`, the frontend uses the browser preview adapter
with fixture data. With the bridge enabled, configuration, characters,
backgrounds, templates, plugin manifest toggles, and chat launch requests go
through Python services.

The Tools page is also bridge-backed: sprite prompt generation, batch sprite
generation, crop, and background removal call the same Python modules used by
the PySide settings window.

In browser development mode, character/background import uploads `.char`, `.cha`,
or `.bg` packages to the bridge. Export endpoints create packages under
`output/` and return a download URL; the React platform opens that URL for the
browser to download.

Plugin discovery and installation stay behind the platform boundary. The bridge
serves `GET /api/plugins/registry` from the existing plugin registry code and
adds local downloaded/installed status. Installation is task-based:
`POST /api/plugins/install` returns a task snapshot, the React adapter polls
`GET /api/tasks/:id`, and the plugin page renders download, dependency-install,
completion, and failure status from that stream.

Chat chrome theme JSON also stays behind the platform boundary. The bridge
serves `GET /api/chat/theme`; React parses the payload through an allowlist into
CSS variables for the stage, dialog, option, input, and toolbar chrome.

For isolated write tests, point `--project-root` at a temporary directory with a
`data/` folder. The bridge resolves YAML paths from that root while importing
Python modules from this repository.

## Boundaries

- `app` owns routing, providers, shell layout, and app-level state.
- `shared` owns design tokens, reusable UI, async/query setup, i18n, and platform adapters.
- `entities` owns domain types, schemas, repositories, and serialization.
- `features` owns page-level behavior, mutations, task state, and composition.
- React components do not read YAML, call Python modules, or access Tauri/Electron APIs directly.
- Plugins render only into declared slots from `entities/plugin/slots.tsx`; UI contributions must declare id, title, slot, permissions, render function, and optional config schema.
- UI copy reads from `shared/i18n`; `SystemSettingsPage` updates the app language state after config load/save.
- Schema-driven settings forms validate required fields, URL shape, numeric ranges, and basic path safety before save.

The browser preview adapter uses in-memory fixture data so the UI can be developed
before the desktop IPC bridge is wired. A desktop container should inject
`window.__SHINSEKAI_IPC__` with the same contract.

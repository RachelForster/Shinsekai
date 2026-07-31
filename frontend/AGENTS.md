# AGENTS.md

## CI Failure Investigation

When a user reports a CI or test failure from a GitHub Actions job, inspect the exact job log before inferring the fix from local commands. Identify the failing workflow step, command, test file, assertion, and checked-out commit, then reproduce that command or the smallest failing test locally when possible.

If local results differ from CI or the failure appears timing-dependent, treat it as a product or test race until proven otherwise. Investigate the readiness and data-flow invariant in the code, not only the failed assertion. Fix the underlying invariant so rendered UI, enabled state, readiness checks, saved state, and submitted payload derive from the same source of truth. Only then run the relevant local checks and push.

## Cross-Platform Desktop Features

When adding desktop or React stage features, treat window-manager behavior, transparent windows, click-through, drag/resize, path handling, process spawning, and bundled runtime files as platform-specific until verified on Windows, macOS, and Linux.

Do not assume a Linux-tested Tauri/WebView feature is safe on Windows. In particular, Windows WebView2 transparent windows can become unusable if `set_ignore_cursor_events(true)` is enabled from React event handlers and the app relies on later WebView pointer events to recover. Gate these features behind explicit platform-capability checks, keep a non-click-through fallback, and add tests that assert unsupported platforms do not enter the risky state.

If a failure is not caused by platform compatibility, record the invariant that was violated here before implementing new features. Prefer a single source of truth for rendered UI state, enabled/disabled controls, saved config, and submitted runtime payloads.

## Runtime Dependency Failures

When Windows diagnostics show React stage launching but freezing or becoming inert, inspect `logs/main.log` and `logs/chat/*.jsonl` before assuming a frontend bug. A launch that returns 200 can still fail immediately if `main.py` exits during import, for example `ModuleNotFoundError: No module named 'opencc'`.

Treat the managed runtime as ready only when required distributions and imports from `requirements-runtime-core.txt` and `runtime_manifest.json` both pass in the same Python executable that will run chat. Surface `runtimeDependencyError` wherever the user can land, including React stage, and keep an install or repair action visible instead of leaving the stage in an idle/error-looking state.

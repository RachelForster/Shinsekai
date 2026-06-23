# Contributing to Shinsekai

Thanks for your interest in contributing. We're happy you're here.

## Before you code

1. **Open an issue first.** Tell us what you want to do and why. This avoids the disappointment of writing code that doesn't fit the project direction. Wait for a maintainer to respond before starting — we usually reply quickly.

2. **Keep it focused.** One PR, one concern. If your change grows beyond a few hundred lines, it's likely a good candidate for splitting into smaller, reviewable pieces. If you're unsure how to split it, mention it in the issue and we'll help.

## Pull request guidelines

- Link each PR to an existing issue in the description.
- Place new scripts alongside the module they support, rather than in top-level directories like `scripts/` or `assets/`. This keeps the repo organized for everyone.
- Follow the existing code style. Include relevant unit tests, and run `pytest` before pushing.
- Keep optional plugin business tests with the plugin package or plugin repository. The main repository should only test shared SDK/host behavior, using committed fixtures instead of importing ignored local plugins from `plugins/`.
- If you add a new dependency, briefly explain why it's needed in the issue.

## Local presubmit hooks

Install the repository hooks once per clone:

```bash
git config core.hooksPath .githooks
```

The `commit-msg` hook requires commit titles to follow Conventional Commits:

```text
<type>(optional-scope)!: summary
```

Allowed types are `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, and `revert`.

The `pre-push` hook validates the titles of commits being pushed, then runs:

- `python -m pytest -v --tb=short --strict-markers -p no:warnings`
- `pnpm format:check`
- `pnpm lint:types`
- `pnpm test`

Use `SKIP_PRESUBMIT=1 git push` only for emergencies.

If your shell's default Python is not the project environment, set `SHINSEKAI_PRESUBMIT_PYTHON` before pushing, for example:

```bash
SHINSEKAI_PRESUBMIT_PYTHON="conda run -n shinsekai python" git push
```

## Test coverage

Coverage checks are separate from the regular pre-push test run. Use them when a change adds behavior, changes existing behavior, or when you need to understand which files still lack tests.

### Frontend coverage

Run frontend coverage from the `frontend/` directory:

```bash
cd frontend
pnpm test:coverage
```

This runs `vitest run --coverage` and uses the coverage settings in `frontend/vite.config.ts`. The report covers `frontend/src/**/*.{ts,tsx}` and excludes test files, TypeScript declaration files, and `frontend/src/main.tsx`.

The frontend coverage gate currently requires at least 90% overall line coverage and 90% overall statement coverage. The local default is 90%, and the React Frontend GitHub Actions workflow also sets `FRONTEND_COVERAGE_THRESHOLD=90` before running `pnpm test:coverage`. If either number drops below 90%, `pnpm test:coverage` fails locally and in CI. Keep the coverage at or above that threshold when adding or changing frontend code.

Useful frontend report files:

- Text summary: printed in the terminal.
- HTML report: `frontend/coverage/index.html`.
- Machine-readable summary: `frontend/coverage/coverage-summary.json`.
- LCOV report for external tools: `frontend/coverage/lcov.info`.

When coverage fails, open the HTML report first. Files and lines highlighted in red are the missing test areas. Prefer adding focused tests next to the relevant feature, app, entity, shared, or platform test group under `frontend/src/test/`.

### Python coverage

Install the Python development dependencies before running coverage:

```bash
python -m pip install -r requirements-dev.txt
```

Run Python coverage from the repository root:

```bash
python -m pytest --cov --cov-config=.coveragerc --cov-report=term-missing --cov-report=html --cov-report=xml --cov-report=json
```

If your default Python is not the project environment, run the same command through the project environment, for example:

```bash
conda run -n shinsekai python -m pytest --cov --cov-config=.coveragerc --cov-report=term-missing --cov-report=html --cov-report=xml --cov-report=json
```

The Python coverage source and output paths are configured in `.coveragerc`. The configured source set includes the main runtime packages such as `core`, `frontend_bridge_core`, `llm`, `sdk`, `tools`, `ui`, and related modules, while excluding tests and generated files.

Useful Python report files:

- Text summary with missing lines: printed in the terminal by `term-missing`.
- HTML report: `coverage/python/html/index.html`.
- XML report: `coverage/python/coverage.xml`.
- JSON report: `coverage/python/coverage.json`.

For Python changes, prefer running the smallest relevant pytest target first while developing, then run the full coverage command before opening or updating a PR when the change affects shared behavior.

## After merging

- Your branch can be deleted (the maintainer will handle this if you don't have permission).
- Close the linked issue if GitHub didn't auto-close it.

---

If anything in this guide is unclear, feel free to open an issue and ask. We'd rather have that conversation than see you struggle with the process.

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

## After merging

- Your branch can be deleted (the maintainer will handle this if you don't have permission).
- Close the linked issue if GitHub didn't auto-close it.

---

If anything in this guide is unclear, feel free to open an issue and ask. We'd rather have that conversation than see you struggle with the process.

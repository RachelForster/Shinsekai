# Contributing to Shinsekai

Thanks for your interest in contributing. To keep things manageable, please follow these rules.

## Before you code

1. **Open an issue first.** Describe what you want to do and why. Wait for maintainer acknowledgment before starting work. Unsolicited PRs without a prior issue may be closed without review.

2. **Keep scope small.** A PR should address one concern. If your change exceeds a few hundred lines, it almost certainly needs to be split up or discussed further.

## Pull request guidelines

- Each PR must be linked to an existing issue.
- Do not dump unrelated files into top-level directories (e.g., `scripts/`, `assets/`). New scripts belong under a feature-specific directory or alongside the module they support.
- Follow the existing code style. Add related unit tests, and run `pytest` before pushing.
- If you add a new dependency, explain why it is necessary in the issue.

## After merging

- Delete your branch (the maintainer will handle this if you don't have permission).
- Close the linked issue if it was not auto-closed.

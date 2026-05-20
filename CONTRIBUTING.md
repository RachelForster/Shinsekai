# Contributing to Shinsekai

Thanks for your interest in contributing. We're happy you're here.

## Before you code

1. **Open an issue first.** Tell us what you want to do and why. This avoids the disappointment of writing code that doesn't fit the project direction. Wait for a maintainer to respond before starting — we usually reply quickly.

2. **Keep it focused.** One PR, one concern. If your change grows beyond a few hundred lines, it's likely a good candidate for splitting into smaller, reviewable pieces. If you're unsure how to split it, mention it in the issue and we'll help.

## Pull request guidelines

- Link each PR to an existing issue in the description.
- Place new scripts alongside the module they support, rather than in top-level directories like `scripts/` or `assets/`. This keeps the repo organized for everyone.
- Follow the existing code style. Include relevant unit tests, and run `pytest` before pushing.
- If you add a new dependency, briefly explain why it's needed in the issue.

## After merging

- Your branch can be deleted (the maintainer will handle this if you don't have permission).
- Close the linked issue if GitHub didn't auto-close it.

---

If anything in this guide is unclear, feel free to open an issue and ask. We'd rather have that conversation than see you struggle with the process.

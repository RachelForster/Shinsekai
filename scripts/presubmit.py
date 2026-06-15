#!/usr/bin/env python3
"""Local presubmit checks for Git hooks."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ZERO_SHA = "0" * 40
COMMIT_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
CONVENTIONAL_TITLE_RE = re.compile(
    rf"^({'|'.join(COMMIT_TYPES)})(\([A-Za-z0-9._/-]+\))?!?: .+"
)
VERSION_BUMP_RE = re.compile(r"^Bump version to \d+\.\d+\.\d+")
MERGE_RE = re.compile(r"^Merge (branch|pull request|remote-tracking branch) .+")
REVERT_RE = re.compile(r'^Revert ".+"')
MAX_TITLE_LENGTH = 100


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: presubmit.py <commit-msg|pre-push> [...]", file=sys.stderr)
        return 2

    command = sys.argv[1]
    if command == "commit-msg":
        if len(sys.argv) != 3:
            print("usage: presubmit.py commit-msg <message-file>", file=sys.stderr)
            return 2
        return validate_commit_message_file(Path(sys.argv[2]))
    if command == "pre-push":
        remote_name = sys.argv[2] if len(sys.argv) >= 3 else ""
        remote_url = sys.argv[3] if len(sys.argv) >= 4 else ""
        return pre_push(remote_name, remote_url, sys.stdin.read())

    print(f"unknown presubmit command: {command}", file=sys.stderr)
    return 2


def pre_push(remote_name: str, remote_url: str, hook_input: str) -> int:
    if os.environ.get("SKIP_PRESUBMIT") == "1":
        print("presubmit: skipped because SKIP_PRESUBMIT=1")
        return run_git_lfs_pre_push(remote_name, remote_url, hook_input)

    commits = commits_from_pre_push_input(remote_name, hook_input)
    if commits:
        result = validate_commit_titles(commits)
        if result != 0:
            return result
    else:
        print("presubmit: no branch commits to validate")

    checks = [
        (
            "Python tests",
            python_test_command()
            + [
                "-m",
                "pytest",
                "-v",
                "--tb=short",
                "--strict-markers",
                "-p",
                "no:warnings",
                "-o",
                f"cache_dir={pytest_cache_dir()}",
            ],
            ROOT,
        ),
    ]

    if (FRONTEND / "package.json").exists():
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            print("presubmit: pnpm is required for frontend checks but was not found.", file=sys.stderr)
            return 1
        checks.extend(
            [
                ("Frontend format", [pnpm, "format:check"], FRONTEND),
                ("Frontend type check", [pnpm, "lint:types"], FRONTEND),
                ("Frontend unit tests", [pnpm, "test"], FRONTEND),
            ]
        )

    for label, command, cwd in checks:
        result = run_check(label, command, cwd)
        if result != 0:
            return result

    return run_git_lfs_pre_push(remote_name, remote_url, hook_input)


def commits_from_pre_push_input(remote_name: str, hook_input: str) -> list[str]:
    commits: list[str] = []
    seen: set[str] = set()

    for raw_line in hook_input.splitlines():
        parts = raw_line.split()
        if len(parts) < 4:
            continue

        local_ref, local_sha, _remote_ref, remote_sha = parts[:4]
        if local_sha == ZERO_SHA or not local_ref.startswith("refs/heads/"):
            continue

        if remote_sha == ZERO_SHA:
            rev_args = ["rev-list", local_sha, "--not", "--remotes"]
            if remote_name and re.fullmatch(r"[A-Za-z0-9._/-]+", remote_name):
                rev_args[-1] = f"--remotes={remote_name}"
        else:
            rev_args = ["rev-list", f"{remote_sha}..{local_sha}", "--not", "--remotes"]

        result = git(rev_args, capture_output=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr, end="")
            raise SystemExit(result.returncode)

        for sha in result.stdout.splitlines():
            if sha and sha not in seen:
                seen.add(sha)
                commits.append(sha)

    return commits


def validate_commit_message_file(message_file: Path) -> int:
    try:
        lines = message_file.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = message_file.read_text().splitlines()

    title = next((line.strip() for line in lines if line.strip() and not line.startswith("#")), "")
    return validate_title(title)


def validate_commit_titles(commits: list[str]) -> int:
    invalid: list[tuple[str, str]] = []

    for sha in commits:
        result = git(["log", "-1", "--format=%s", sha], capture_output=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr, end="")
            return result.returncode
        title = result.stdout.strip()
        if not is_valid_title(title):
            invalid.append((sha[:12], title))

    if invalid:
        print("presubmit: commit title check failed.", file=sys.stderr)
        for sha, title in invalid:
            print(f"  {sha} {title}", file=sys.stderr)
        print_commit_title_help()
        return 1

    print(f"presubmit: validated {len(commits)} commit title(s)")
    return 0


def validate_title(title: str) -> int:
    if is_valid_title(title):
        return 0

    print(f"presubmit: invalid commit title: {title}", file=sys.stderr)
    print_commit_title_help()
    return 1


def is_valid_title(title: str) -> bool:
    if not title or len(title) > MAX_TITLE_LENGTH:
        return False
    if title.lower().startswith(("wip", "fixup!", "squash!")):
        return False
    return bool(
        CONVENTIONAL_TITLE_RE.match(title)
        or MERGE_RE.match(title)
        or REVERT_RE.match(title)
        or VERSION_BUMP_RE.match(title)
    )


def print_commit_title_help() -> None:
    print(
        "\nCommit title format:\n"
        "  <type>(optional-scope)!: summary\n\n"
        f"Allowed types: {', '.join(COMMIT_TYPES)}\n"
        "Examples:\n"
        "  feat(plugin): add registry cache\n"
        "  fix: handle missing runtime manifest\n"
        "  chore!: drop legacy config key\n"
        f"Keep the title at or below {MAX_TITLE_LENGTH} characters.\n",
        file=sys.stderr,
    )


def run_check(label: str, command: list[str], cwd: Path) -> int:
    print(f"\n==> {label}")
    print(f"    {' '.join(command)}")
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(command, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"presubmit: {label} failed.", file=sys.stderr)
    return result.returncode


def python_test_command() -> list[str]:
    override = os.environ.get("SHINSEKAI_PRESUBMIT_PYTHON")
    if override:
        return shlex.split(override, posix=os.name != "nt")
    return [sys.executable]


def pytest_cache_dir() -> str:
    return str(Path(tempfile.gettempdir()) / "shinsekai-pytest-cache")


def run_git_lfs_pre_push(remote_name: str, remote_url: str, hook_input: str) -> int:
    if shutil.which("git-lfs") is None:
        if repository_uses_lfs():
            print("presubmit: git-lfs is required for this repository but was not found.", file=sys.stderr)
            return 1
        return 0

    result = subprocess.run(
        ["git", "lfs", "pre-push", remote_name, remote_url],
        cwd=ROOT,
        input=hook_input,
        text=True,
    )
    return result.returncode


def repository_uses_lfs() -> bool:
    attributes = ROOT / ".gitattributes"
    if not attributes.exists():
        return False
    try:
        return "filter=lfs" in attributes.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "filter=lfs" in attributes.read_text(errors="ignore")


def git(args: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=capture_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())

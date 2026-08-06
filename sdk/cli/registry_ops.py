"""Helpers for `plugins.json` in Shinsekai-Plugin-Registry."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from sdk.file_transactions import read_text_without_links
from sdk.process_launch import (
    capture_command_executable,
    capture_launch_directory,
    run_with_stable_paths,
)
from sdk.path_contract import (
    require_directory_without_links,
    resolve_managed_project_path,
)


def exact_registry_entry(entry: str) -> str:
    raw = str(entry or "")
    if not raw or raw != raw.strip() or any(
        ord(character) < 32
        or ord(character) == 127
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in raw
    ):
        raise ValueError(
            "registry entry is required and must not contain surrounding whitespace "
            "or control characters"
        )
    return raw


def normalize_repo_slug(repo: str) -> str:
    raw = str(repo or "")
    if (
        not raw
        or raw != raw.strip()
        or raw.startswith("/")
        or raw.endswith("/")
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw
        )
    ):
        raise ValueError("repo must be an exact owner/name slug")
    parts = raw.split("/")
    if (
        len(parts) != 2
        or any(part in {"", ".", ".."} or part != part.strip() for part in parts)
        or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts)
    ):
        raise ValueError("repo must be an exact owner/name slug")
    return raw


def load_registry_json(path: Path) -> list[dict[str, Any]]:
    text = read_text_without_links(path)

    def _relax_trailing_commas(s: str) -> str:
        return re.sub(r",(\s*[}\]])", r"\1", s.strip())

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = json.loads(_relax_trailing_commas(text))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: root must be a JSON array")
    return [x for x in raw if isinstance(x, dict)]


def dump_registry_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2) + "\n"


def validate_rows(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        name = str(row.get("name") or "").strip()
        repo = str(row.get("repo") or "").strip()
        if not name and not repo:
            raise ValueError(f"registry[{index}] needs at least name or repo")


def merge_registry_entry(
    rows: list[dict[str, Any]],
    *,
    name: str,
    author: str,
    repo: str,
    description: str,
    entry: str,
    replace: bool,
) -> list[dict[str, Any]]:
    slug = normalize_repo_slug(repo)
    new_row = {
        "name": name.strip(),
        "author": author.strip(),
        "repo": slug,
        "description": description.strip(),
        "entry": exact_registry_entry(entry),
    }

    out: list[dict[str, Any]] = []
    replaced_or_skipped = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = row.get("repo", "")
        if isinstance(r, str) and normalize_repo_slug(r).casefold() == slug.casefold():
            if replace:
                if not replaced_or_skipped:
                    out.append(dict(new_row))
                    replaced_or_skipped = True
                continue
            raise ValueError(
                f"registry already contains repo {slug!r}; pass --replace to overwrite"
            )
        out.append(dict(row))

    if not replaced_or_skipped:
        out.append(dict(new_row))

    validate_rows(out)
    out.sort(key=lambda d: str(d.get("name") or d.get("repo") or "").lower())
    return out


def run_git_commit(
    registry_root: Path,
    message: str,
    *,
    file_path: str = "plugins.json",
) -> None:
    registry_root = require_directory_without_links(
        registry_root,
        field="registry clone root",
    )
    raw_file_path = str(file_path)
    if Path(raw_file_path).is_absolute():
        raise ValueError("registry file path must be relative to the registry clone")
    managed_file = resolve_managed_project_path(
        raw_file_path,
        root=registry_root,
    )
    relative_file = managed_file.relative_to(registry_root).as_posix()
    root_snapshot = capture_launch_directory(
        registry_root,
        field="registry clone root",
    )
    git_snapshot = capture_command_executable(
        "git",
        field="git executable",
    )
    run_with_stable_paths(
        [git_snapshot.path, "add", "--", relative_file],
        cwd=root_snapshot,
        executable=git_snapshot,
        run_factory=subprocess.run,
        check=True,
    )
    run_with_stable_paths(
        [git_snapshot.path, "commit", "-m", message],
        cwd=root_snapshot,
        executable=git_snapshot,
        run_factory=subprocess.run,
        check=True,
    )

"""Helpers for `plugins.json` in Shinsekai-Plugin-Registry."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from core.plugins.registry_catalog import parse_registry_plugins


def normalize_repo_slug(repo: str) -> str:
    parts = [p.strip() for p in repo.strip().strip("/").split("/") if p.strip()]
    return "/".join(parts).lower()


def load_registry_json(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")

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
    parse_registry_plugins(rows)


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
    if not slug or slug.count("/") < 1:
        raise ValueError("repo must look like owner/name")

    new_row = {
        "name": name.strip(),
        "author": author.strip(),
        "repo": repo.strip().strip("/"),
        "description": description.strip(),
        "entry": entry.strip(),
    }

    out: list[dict[str, Any]] = []
    replaced_or_skipped = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        r = row.get("repo", "")
        if isinstance(r, str) and normalize_repo_slug(r) == slug:
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


def run_git_commit(registry_root: Path, message: str) -> None:
    subprocess.run(
        ["git", "add", "plugins.json"],
        cwd=registry_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=registry_root,
        check=True,
    )

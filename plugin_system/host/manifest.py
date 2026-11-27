"""Plugin manifest YAML parsing, entry normalization, and update helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def read_plugin_manifest_items(path: Path) -> list[dict[str, Any]]:
    """Return manifest rows as mutable dicts, keeping valid ``entry`` rows in order."""
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to parse plugin manifest %s", path)
        return []
    if raw is None or not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry = item.get("entry")
        if not isinstance(entry, str) or not entry.strip():
            continue
        out.append(dict(item))
    return out


def write_plugin_manifest_items(items: list[dict[str, Any]], path: Path) -> None:
    """Overwrite manifest with ``items`` (YAML list of mappings)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        items,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    path.write_text(text, encoding="utf-8")


def set_plugin_manifest_enabled(entry: str, enabled: bool, path: Path) -> bool:
    """Set ``enabled`` on the manifest row whose ``entry`` matches (strip-wise)."""
    items = read_plugin_manifest_items(path)
    norm = entry.strip()
    changed = False
    for item in items:
        item_entry = item.get("entry")
        if isinstance(item_entry, str) and item_entry.strip() == norm:
            item["enabled"] = bool(enabled)
            changed = True
            break
    if changed:
        write_plugin_manifest_items(items, path)
    return changed


def normalize_manifest_entry(entry: str) -> str:
    """Ensure downloaded plugin ``entry`` uses the ``plugins.`` module prefix."""
    norm = entry.strip()
    if not norm or norm.startswith("plugins."):
        return norm
    return f"plugins.{norm}"


def remove_plugin_manifest_entry(entry: str, path: Path) -> bool:
    """Remove the manifest row whose ``entry`` matches (strip-wise)."""
    norm = entry.strip()
    items = read_plugin_manifest_items(path)
    kept: list[dict[str, Any]] = []
    removed = False
    for item in items:
        item_entry = item.get("entry")
        if isinstance(item_entry, str) and item_entry.strip() == norm:
            removed = True
            continue
        kept.append(item)
    if not removed:
        return False
    write_plugin_manifest_items(kept, path)
    return True


def infer_plugin_package_directory(entry: str) -> Path | None:
    """Map manifest ``entry`` module path to ``plugins/<top-level-package>/``."""
    raw = entry.strip()
    if not raw:
        return None
    mod = raw.split(":", 1)[0].strip()
    if not mod.startswith("plugins."):
        mod = normalize_manifest_entry(mod)
    if not mod.startswith("plugins."):
        return None
    rest = mod[len("plugins.") :]
    if not rest:
        return None
    top = rest.split(".", 1)[0].strip()
    if not top:
        return None
    return Path("plugins") / top


def append_plugin_manifest_entry_if_missing(
    entry: str,
    *,
    enabled: bool = True,
    path: Path,
) -> str:
    """Append ``- entry: ...`` row if not already present (``added`` | ``exists`` | ``empty``)."""
    norm = normalize_manifest_entry(entry)
    if not norm:
        return "empty"
    items = read_plugin_manifest_items(path)
    for item in items:
        item_entry = item.get("entry")
        if isinstance(item_entry, str) and item_entry.strip() == norm:
            return "exists"
    items.append({"entry": norm, "enabled": bool(enabled)})
    write_plugin_manifest_items(items, path)
    return "added"

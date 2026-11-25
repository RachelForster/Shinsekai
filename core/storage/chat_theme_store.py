"""Read chat UI theme manifests through unified storage boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.paths import source_root
from core.storage.layout import StorageLayout
from sdk.path_utils import reject_control_chars, safe_existing_file_path


def read_chat_theme_manifest(project_root: Path, theme_id: str) -> dict[str, Any]:
    """Safely load a chat UI theme manifest from project data or built-in assets."""
    clean_id = str(theme_id or "").strip()
    if not clean_id or "/" in clean_id or "\\" in clean_id or ".." in clean_id:
        return {}
    try:
        clean_id = reject_control_chars(clean_id, field="themeId")
    except ValueError:
        return {}

    user_themes_root = StorageLayout(project_root).data_dir / "chat_ui_themes"
    builtin_themes_root = source_root() / "assets" / "chat_ui_themes"
    for themes_root in (user_themes_root, builtin_themes_root):
        try:
            manifest_path = safe_existing_file_path(
                Path(clean_id) / "theme.json",
                roots=[themes_root],
                field="chat theme manifest",
            )
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, PermissionError, ValueError):
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}


__all__ = ["read_chat_theme_manifest"]

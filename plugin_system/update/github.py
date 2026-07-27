"""Install plugin source archives fetched from GitHub."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from core.app_update.github_bundle import (
    RefKindApi,
    download_zip_extract_top_folder,
    merge_source_tree_into,
    normalize_repo_slug_str,
    resolve_ref_for_download,
)
from plugin_system.registry.download import sanitize_plugins_directory_name


def install_github_plugin_under_plugins(
    repo: str,
    *,
    catalog_display_name: str,
    ref_kind: RefKindApi,
    tag_name: str,
    overwrite: bool,
    plugins_parent: Path | None,
    progress: Callable[[int, int | None], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> Path:
    """Download a GitHub source archive and install it below ``plugins/``."""
    slug = normalize_repo_slug_str(repo)
    ref_kind_value, ref_name = resolve_ref_for_download(slug, ref_kind, tag_name)
    temporary_parent, extracted_top = download_zip_extract_top_folder(
        slug,
        ref_heads_or_tags=ref_kind_value,
        ref_name=ref_name,
        progress=progress,
        on_phase=on_phase,
        timeout_sec=300.0,
    )
    try:
        parent = Path(plugins_parent) if plugins_parent is not None else Path("plugins")
        parent.mkdir(parents=True, exist_ok=True)
        directory_name = sanitize_plugins_directory_name(
            (catalog_display_name or "").strip()
        )
        if not directory_name:
            directory_name = sanitize_plugins_directory_name(slug.rsplit("/", 1)[-1])
        destination = parent / directory_name

        if destination.is_dir():
            if overwrite:
                shutil.rmtree(destination, ignore_errors=True)
            else:
                merge_source_tree_into(destination, extracted_top)
                return destination.resolve()

        shutil.move(str(extracted_top), str(destination))
        return destination.resolve()
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)

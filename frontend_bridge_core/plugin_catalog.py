from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .security import safe_child_path


def _resolve_loaded_plugin_for_manifest_entry(entry: str, manager: Any | None) -> Any | None:
    if manager is None:
        return None
    raw = entry.strip()
    try:
        plugins = manager.plugins
    except Exception:
        return None
    for plugin in plugins:
        cls = plugin.__class__
        full = f"{cls.__module__}:{cls.__qualname__}"
        if full == raw:
            return plugin
        if ":" not in raw and cls.__module__ == raw:
            return plugin
    return None


def _display_title_for_offline_plugin_entry(entry: str) -> str:
    value = entry.strip()
    if ":" in value:
        return value.rpartition(":")[2]
    return value.rpartition(".")[2] if "." in value else value


def _apply_registry_author_fallback(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(not str(row.get("author") or "").strip() for row in rows):
        return rows
    try:
        from core.plugins.registry_catalog import fetch_registry_plugins
        from core.plugins.registry_download import normalize_manifest_entry, normalize_repo_slug

        records = fetch_registry_plugins(timeout_sec=5.0)
    except Exception:
        return rows

    authors_by_entry: dict[str, str] = {}
    authors_by_repo: dict[str, str] = {}
    for record in records:
        author = str(getattr(record, "author", "") or "").strip()
        if not author:
            continue
        entry = normalize_manifest_entry(str(getattr(record, "entry", "") or ""))
        repo = normalize_repo_slug(str(getattr(record, "repo", "") or ""))
        if entry:
            authors_by_entry.setdefault(entry, author)
        if repo:
            authors_by_repo.setdefault(repo, author)

    for row in rows:
        if str(row.get("author") or "").strip():
            continue
        install = row.get("install") if isinstance(row.get("install"), dict) else {}
        entries = [
            str(row.get("entry") or ""),
            str(install.get("entry") or ""),
        ]
        for entry in entries:
            author = authors_by_entry.get(normalize_manifest_entry(entry))
            if author:
                row["author"] = author
                break
        if str(row.get("author") or "").strip():
            continue
        repo_author = authors_by_repo.get(normalize_repo_slug(str(install.get("repo") or "")))
        if repo_author:
            row["author"] = repo_author
    return rows


def _plugin_rows(plugin_load: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        from core.plugins.plugin_host import (
            collect_chat_ui_contributions,
            collect_frontend_config_contributions,
            collect_frontend_page_contributions,
            collect_settings_contributions,
            collect_tools_tab_contributions,
            get_plugin_manager,
            infer_plugin_package_directory,
            read_plugin_manifest_items,
        )
        from core.plugins.registry_download import load_plugin_install_metadata
    except Exception:
        return []

    manager = get_plugin_manager()
    settings_by_plugin: dict[str, list[str]] = {}
    tools_by_plugin: dict[str, list[str]] = {}
    chat_by_plugin: dict[str, list[str]] = {}
    frontend_settings_by_plugin: dict[str, list[str]] = {}
    frontend_tools_by_plugin: dict[str, list[str]] = {}
    for contribution in collect_settings_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        label = str(getattr(contribution, "nav_label", "") or "").strip()
        if plugin_id and label:
            settings_by_plugin.setdefault(plugin_id, []).append(label)
    for contribution in collect_tools_tab_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        label = str(getattr(contribution, "title", "") or "").strip()
        if plugin_id and label:
            tools_by_plugin.setdefault(plugin_id, []).append(label)
    for contribution in collect_chat_ui_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        placement = str(getattr(contribution, "placement", "") or "").strip()
        if plugin_id and placement:
            chat_by_plugin.setdefault(plugin_id, []).append(placement)
    for contribution in collect_frontend_config_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        label = str(getattr(contribution, "title", "") or "").strip()
        kind = str(getattr(contribution, "kind", "") or "").strip()
        if not plugin_id or not label:
            continue
        if kind == "tools":
            frontend_tools_by_plugin.setdefault(plugin_id, []).append(label)
        else:
            frontend_settings_by_plugin.setdefault(plugin_id, []).append(label)
    for contribution in collect_frontend_page_contributions():
        plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
        label = str(getattr(contribution, "title", "") or "").strip()
        kind = str(getattr(contribution, "kind", "") or "").strip()
        if not plugin_id or not label:
            continue
        if kind == "tools":
            frontend_tools_by_plugin.setdefault(plugin_id, []).append(label)
        else:
            frontend_settings_by_plugin.setdefault(plugin_id, []).append(label)

    def _row(
        *,
        author: str,
        description: str,
        enabled: bool,
        entry: str,
        permissions: list[Any] | None,
        plugin_id: str,
        title: str,
        version: str,
        directory: str = "",
        load_error: str = "",
        loaded: bool = True,
    ) -> dict[str, Any]:
        settings_pages = list(dict.fromkeys([
            *settings_by_plugin.get(plugin_id, []),
            *frontend_settings_by_plugin.get(plugin_id, []),
        ]))
        tools_tabs = list(dict.fromkeys([
            *tools_by_plugin.get(plugin_id, []),
            *frontend_tools_by_plugin.get(plugin_id, []),
        ]))
        slots: set[str] = set()
        if settings_pages:
            slots.add("settings-extension")
        if tools_tabs:
            slots.add("settings-tools")
        if chat_by_plugin.get(plugin_id):
            slots.add("chat-dialog-actions")
            slots.add("chat-output")
        if not slots:
            slots.add("settings-extension")
        return {
            "author": author,
            "description": description,
            "directory": directory,
            "enabled": enabled,
            "entry": entry,
            "id": plugin_id,
            "loadError": load_error,
            "loaded": loaded,
            "permissions": list(permissions or []),
            "settingsPages": settings_pages,
            "slots": sorted(slots),
            "title": title,
            "toolsTabs": tools_tabs,
            "version": version,
        }

    rows: list[dict[str, Any]] = []
    seen_plugin_ids: set[str] = set()
    manifest_items = read_plugin_manifest_items()
    if manifest_items:
        for item in manifest_items:
            entry = str(item.get("entry") or "").strip()
            if not entry:
                continue
            plugin = _resolve_loaded_plugin_for_manifest_entry(entry, manager)
            enabled = bool(item.get("enabled", True))
            if plugin is not None:
                plugin_id = str(plugin.plugin_id)
                seen_plugin_ids.add(plugin_id)
                version = str(plugin.plugin_version)
                title = str(plugin.plugin_name).strip() or plugin_id
                description = str(plugin.plugin_description or "").strip()
                author = str(plugin.plugin_author or "").strip()
                loaded = True
                load_error = ""
            else:
                plugin_id = entry
                version = "—"
                title = _display_title_for_offline_plugin_entry(entry)
                description = ""
                author = ""
                loaded = False
                if enabled and str((plugin_load or {}).get("status") or "") == "loading":
                    load_error = "插件正在加载，请稍候。"
                else:
                    load_error = "插件配置已启用，但插件代码未安装或导入失败。" if enabled else ""
            slots = set(str(slot) for slot in (item.get("slots") or []) if str(slot).strip())
            directory = infer_plugin_package_directory(entry)
            row = _row(
                author=author,
                description=description,
                directory=directory.as_posix() if directory is not None else "",
                enabled=enabled,
                entry=entry,
                load_error=load_error,
                loaded=loaded,
                permissions=list(item.get("permissions") or []),
                plugin_id=plugin_id,
                title=title,
                version=version,
            )
            if slots:
                row["slots"] = sorted(set(row["slots"]) | slots)
            install_metadata = load_plugin_install_metadata(entry)
            if install_metadata:
                row["install"] = install_metadata
            rows.append(row)
    else:
        for plugin in getattr(manager, "plugins", []) if manager is not None else []:
            plugin_id = str(plugin.plugin_id)
            seen_plugin_ids.add(plugin_id)
            rows.append(
                _row(
                    author=str(plugin.plugin_author or "").strip(),
                    description=str(plugin.plugin_description or "").strip(),
                    directory="",
                    enabled=True,
                    entry="",
                    permissions=[],
                    plugin_id=plugin_id,
                    title=str(plugin.plugin_name).strip() or plugin_id,
                    version=str(plugin.plugin_version),
                )
            )
        for key in sorted(set(settings_by_plugin.keys()) | set(tools_by_plugin.keys())):
            if key in seen_plugin_ids:
                continue
            label = key
            if key.startswith("_:"):
                labels = settings_by_plugin.get(key) or tools_by_plugin.get(key) or [key]
                label = labels[0]
            rows.append(
                _row(
                    author="",
                    description="",
                    directory="",
                    enabled=True,
                    entry="",
                    permissions=[],
                    plugin_id=key,
                    title=label,
                    version="",
                )
            )
    return _apply_registry_author_fallback(rows)


def _plugin_registry_rows() -> list[dict[str, Any]]:
    from core.plugins.registry_catalog import fetch_registry_plugins
    from core.plugins.registry_download import load_downloaded_repos, normalize_manifest_entry, normalize_repo_slug

    installed_entries = {
        normalize_manifest_entry(str(row.get("entry") or row.get("id") or ""))
        for row in _plugin_rows()
        if str(row.get("entry") or row.get("id") or "").strip()
    }
    downloaded_repos = load_downloaded_repos()
    rows: list[dict[str, Any]] = []
    for rec in fetch_registry_plugins():
        entry = str(rec.entry or "").strip()
        repo = str(rec.repo or "").strip()
        norm_entry = normalize_manifest_entry(entry) if entry else ""
        norm_repo = normalize_repo_slug(repo)
        installed = bool(norm_entry and norm_entry in installed_entries)
        downloaded = bool(norm_repo and norm_repo in downloaded_repos)
        rows.append(
            {
                "author": str(rec.author or ""),
                "commitSha": str(getattr(rec, "commit_sha", "") or ""),
                "description": str(rec.description or ""),
                "displayName": str(getattr(rec, "display_name", "") or rec.name or repo),
                "downloadUrl": str(getattr(rec, "download_url", "") or ""),
                "downloaded": downloaded,
                "entry": entry,
                "forks": int(getattr(rec, "forks", 0) or 0),
                "id": str(getattr(rec, "id", "") or rec.name or repo),
                "installed": installed,
                "logo": str(getattr(rec, "logo", "") or ""),
                "name": str(rec.name or repo),
                "packageR2Key": str(getattr(rec, "package_r2_key", "") or ""),
                "packageSha256": str(getattr(rec, "package_sha256", "") or ""),
                "packageSize": getattr(rec, "package_size", None),
                "packageSource": str(getattr(rec, "package_source", "") or ""),
                "packageUrl": str(getattr(rec, "package_url", "") or ""),
                "readmeUrl": str(getattr(rec, "readme_url", "") or ""),
                "repo": repo,
                "securityScan": dict(getattr(rec, "security_scan", None) or {}),
                "sha256": str(getattr(rec, "sha256", "") or ""),
                "lowestShinsekaiVersion": str(
                    getattr(rec, "lowest_shinsekai_version", "")
                    or getattr(rec, "shinsekai_version", "")
                    or ""
                ),
                "shortDescription": str(getattr(rec, "short_description", "") or ""),
                "size": getattr(rec, "size", None),
                "socialLink": str(getattr(rec, "social_link", "") or ""),
                "sourceUrl": str(getattr(rec, "source_url", "") or ""),
                "stars": int(getattr(rec, "stars", 0) or 0),
                "tags": list(getattr(rec, "tags", None) or []),
                "trustLevel": str(getattr(rec, "trust_level", "") or "community"),
                "updatedAt": str(getattr(rec, "updated_at", "") or ""),
                "verified": bool(getattr(rec, "verified", False)),
                "version": str(getattr(rec, "version", "") or ""),
                "review": getattr(rec, "review", None),
            }
        )
    return rows


def _set_plugin_enabled(plugin_id: str, enabled: bool) -> dict[str, Any]:
    from core.plugins.plugin_host import set_plugin_manifest_enabled

    if not set_plugin_manifest_enabled(plugin_id, enabled):
        raise KeyError(f"plugin not found: {plugin_id}")
    for row in _plugin_rows():
        if row["entry"] == plugin_id or row["id"] == plugin_id:
            return row
    raise KeyError(f"plugin not found: {plugin_id}")


def _uninstall_plugin(plugin_id: str) -> dict[str, Any]:
    from core.plugins.plugin_host import infer_plugin_package_directory, remove_plugin_manifest_entry
    from core.plugins.registry_download import unmark_repo_for_manifest_entry

    entry = plugin_id.strip()
    if not entry:
        raise ValueError("plugin id is required")
    row_title = entry
    for row in _plugin_rows():
        if row["entry"] == entry or row["id"] == entry:
            row_title = str(row.get("title") or entry)
            break
    if not remove_plugin_manifest_entry(entry):
        raise KeyError(f"plugin not found: {entry}")

    unmark_repo_for_manifest_entry(entry)

    folder_note = ""
    directory = infer_plugin_package_directory(entry)
    if directory is not None and directory.is_dir():
        plugins_root = Path("plugins").resolve()
        try:
            target = directory.resolve()
        except OSError as exc:
            folder_note = str(exc)
        else:
            try:
                relative_target = target.relative_to(plugins_root)
                target = safe_child_path(plugins_root, relative_target.as_posix())
            except ValueError:
                folder_note = f"跳过删除插件目录：{target.as_posix()}"
            if not folder_note and target == plugins_root:
                folder_note = f"跳过删除插件目录：{target.as_posix()}"
            elif not folder_note:
                try:
                    shutil.rmtree(target)
                except OSError as exc:
                    folder_note = str(exc)

    return {
        "folderNote": folder_note,
        "message": f"{row_title} 已从插件清单移除。重启后生效。",
    }

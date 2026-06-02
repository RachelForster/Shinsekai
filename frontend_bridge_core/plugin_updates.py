from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .plugin_catalog import _set_plugin_enabled
from .state import BridgeState
from .tasks import _append_task_log, _update_task


def _app_update_info() -> dict[str, Any]:
    from core.plugins.github_bundle_update import default_app_github_repo_slug, read_local_version, resolve_project_root

    return {
        "repo": default_app_github_repo_slug(),
        "version": read_local_version(resolve_project_root()).strip(),
    }


def _app_update_tags() -> dict[str, Any]:
    from core.plugins.github_bundle_update import default_app_github_repo_slug, fetch_recent_tag_names

    slug = default_app_github_repo_slug().strip()
    if not slug or slug.count("/") < 1:
        raise ValueError("无法解析主程序 GitHub 仓库。")
    return {"tags": fetch_recent_tag_names(slug)}


def _repo_tags(payload: dict[str, Any]) -> dict[str, Any]:
    from core.plugins.github_bundle_update import fetch_recent_tag_names
    from core.plugins.registry_download import normalize_repo_slug

    slug = normalize_repo_slug(str(payload.get("repo") or ""))
    if not slug or slug.count("/") < 1:
        raise ValueError("repo is required")
    return {"tags": fetch_recent_tag_names(slug)}


def _run_app_update(state: BridgeState, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from core.plugins.github_bundle_update import (
        default_app_github_repo_slug,
        overwrite_merge_app_tree,
        read_local_version,
        resolve_project_root,
    )
    from core.plugins.plugin_requirements_install import install_plugin_requirements_txt
    from core.plugins.registry_download import format_download_error

    slug = default_app_github_repo_slug().strip()
    if not slug or slug.count("/") < 1:
        raise ValueError("无法解析主程序 GitHub 仓库。")
    ref_kind = str(payload.get("refKind") or "latest").strip()
    if ref_kind not in {"latest", "head", "tag"}:
        ref_kind = "latest"
    tag_name = str(payload.get("tagName") or "").strip()
    if ref_kind == "tag" and not tag_name:
        raise ValueError("请选择一个有效的 tag。")

    _update_task(state, task_id, message=f"正在下载 {slug} 源码归档。", phase="download", progress=0.05)

    def _progress(current: int, total: int | None) -> None:
        if total:
            ratio = min(max(current / total, 0), 1)
            progress = 0.05 + ratio * 0.58
            message = f"正在下载 {current}/{total} bytes。"
        else:
            progress = 0.2
            message = f"已下载 {current} bytes。"
        _update_task(state, task_id, message=message, phase="download", progress=round(progress, 4))

    def _phase(phase: str) -> None:
        if phase == "extract":
            _update_task(state, task_id, message="正在合并到程序目录。", phase="merge", progress=0.68)

    try:
        overwrite_merge_app_tree(
            slug,
            ref_kind,  # type: ignore[arg-type]
            tag_name,
            progress=_progress,
            on_phase=_phase,
        )
    except Exception as exc:
        raise RuntimeError(format_download_error(exc)) from exc

    _update_task(state, task_id, message="正在检查主程序 requirements.txt。", phase="pip", progress=0.88)

    def _pip_line(line: str) -> None:
        _append_task_log(state, task_id, line)

    pip_code, detail = install_plugin_requirements_txt(resolve_project_root(), on_output_line=_pip_line)
    if detail:
        _append_task_log(state, task_id, detail)
    version = read_local_version(resolve_project_root()).strip()
    result = {
        "detail": detail,
        "message": "文件已合并到当前目录。建议关闭本程序后重新启动以使代码生效。",
        "pipCode": pip_code,
        "version": version,
    }
    _update_task(state, task_id, message=result["message"], phase="completed", progress=1, result=result)
    return result


def _repo_slug_from_source(source: str) -> str:
    from core.plugins.registry_download import normalize_repo_slug

    return normalize_repo_slug(source)


def _is_repo_source(source: str) -> bool:
    raw = source.strip().lower()
    if ":" in source and not (
        raw.startswith("http://") or raw.startswith("https://") or raw.startswith("git@github.com:")
    ):
        return False
    return bool(_repo_slug_from_source(source))


def _lookup_registry_plugin(source: str) -> Any | None:
    repo_slug = _repo_slug_from_source(source).lower()
    source_key = source.strip().lower()
    try:
        from core.plugins.registry_catalog import fetch_registry_plugins
        from core.plugins.registry_download import normalize_repo_slug
    except Exception:
        return None
    try:
        records = fetch_registry_plugins(timeout_sec=12)
    except Exception:
        return None
    for rec in records:
        rec_repo = normalize_repo_slug(rec.repo)
        if rec_repo and rec_repo == repo_slug:
            return rec
        if rec.name.strip().lower() == source_key:
            return rec
        if rec.entry.strip().lower() == source_key:
            return rec
    return None


def _plugin_class_from_file(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "PluginBase":
                return node.name
            if isinstance(base, ast.Attribute) and base.attr == "PluginBase":
                return node.name
    return ""


def _infer_plugin_entry(plugin_root: Path) -> str:
    package = plugin_root.name
    candidates = [plugin_root / "plugin.py", *sorted(plugin_root.glob("*/plugin.py"))]
    for path in candidates:
        if not path.is_file():
            continue
        class_name = _plugin_class_from_file(path)
        if not class_name:
            continue
        rel = path.relative_to(plugin_root).with_suffix("")
        module_parts = [package, *rel.parts]
        if all(part.isidentifier() for part in module_parts):
            return f"plugins.{'.'.join(module_parts)}:{class_name}"
    return ""


def _plugin_result_from_manifest(entry: str) -> dict[str, Any]:
    from core.plugins.plugin_host import append_plugin_manifest_entry_if_missing, normalize_manifest_entry

    append_plugin_manifest_entry_if_missing(entry, enabled=True)
    norm = normalize_manifest_entry(entry)
    return _set_plugin_enabled(norm, True)


def _synthetic_plugin_result(
    *,
    description: str,
    enabled: bool,
    plugin_id: str,
    title: str,
    version: str = "",
) -> dict[str, Any]:
    return {
        "author": "",
        "description": description,
        "directory": "",
        "enabled": enabled,
        "entry": plugin_id,
        "id": plugin_id,
        "loadError": "",
        "loaded": enabled,
        "permissions": [],
        "settingsPages": [],
        "slots": ["settings-extension"],
        "title": title,
        "toolsTabs": [],
        "version": version,
    }


def _install_plugin_source(
    state: BridgeState,
    task_id: str,
    source: str,
    *,
    ref_kind: str = "latest",
    tag_name: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    source = source.strip()
    if not source:
        raise ValueError("plugin id is required")
    ref_kind = ref_kind if ref_kind in {"latest", "head", "tag"} else "latest"
    tag_name = tag_name.strip()
    if ref_kind == "tag" and not tag_name:
        raise ValueError("tagName is required when refKind is tag")

    if not _is_repo_source(source):
        _update_task(
            state,
            task_id,
            message="正在写入插件清单。",
            phase="manifest",
            progress=0.45,
        )
        result = _plugin_result_from_manifest(source)
        _update_task(state, task_id, message="插件清单已更新。", progress=0.9)
        return result

    from core.plugins.github_bundle_update import install_github_plugin_under_plugins
    from core.plugins.plugin_requirements_install import install_plugin_requirements_txt
    from core.plugins.registry_download import format_download_error, mark_repo_downloaded, normalize_repo_slug

    repo_slug = normalize_repo_slug(_repo_slug_from_source(source))
    _update_task(
        state,
        task_id,
        message="正在查询插件索引。",
        phase="registry",
        progress=0.04,
    )
    registry_rec = _lookup_registry_plugin(repo_slug)
    entry = str(getattr(registry_rec, "entry", "") or "").strip()
    display_name = str(getattr(registry_rec, "name", "") or "").strip()
    description = str(getattr(registry_rec, "description", "") or "").strip()

    _update_task(
        state,
        task_id,
        message=f"正在下载 {repo_slug}。",
        phase="download",
        progress=0.08,
    )

    def _progress(current: int, total: int | None) -> None:
        if total:
            ratio = min(max(current / total, 0), 1)
            progress = 0.08 + ratio * 0.55
            message = f"正在下载 {current}/{total} bytes。"
        else:
            progress = 0.18
            message = f"已下载 {current} bytes。"
        _update_task(state, task_id, message=message, phase="download", progress=round(progress, 4))

    def _phase(phase: str) -> None:
        if phase == "extract":
            _update_task(state, task_id, message="正在解压插件源码。", phase="extract", progress=0.66)

    try:
        plugin_root = install_github_plugin_under_plugins(
            repo_slug,
            catalog_display_name=display_name,
            ref_kind=ref_kind,  # type: ignore[arg-type]
            tag_name=tag_name,
            overwrite=overwrite,
            plugins_parent=Path("plugins"),
            progress=_progress,
            on_phase=_phase,
        )
    except Exception as exc:
        raise RuntimeError(format_download_error(exc)) from exc

    _update_task(
        state,
        task_id,
        message="正在检查并安装插件 requirements.txt。",
        phase="pip",
        progress=0.72,
    )

    def _pip_line(line: str) -> None:
        _append_task_log(state, task_id, line)

    pip_code, pip_detail = install_plugin_requirements_txt(plugin_root, on_output_line=_pip_line)
    if pip_code in {"pip_failed", "pip_timeout", "pip_exception"}:
        detail = pip_detail or pip_code
        raise RuntimeError(f"插件依赖安装失败：{detail}")

    if not entry:
        entry = _infer_plugin_entry(plugin_root)

    _update_task(state, task_id, message="正在登记插件安装状态。", phase="manifest", progress=0.9)
    mark_repo_downloaded(repo_slug, manifest_entry=entry or None)
    if entry:
        return _plugin_result_from_manifest(entry)

    return _synthetic_plugin_result(
        description=description or f"源码已下载到 {plugin_root.as_posix()}，但未找到 manifest entry。",
        enabled=False,
        plugin_id=repo_slug,
        title=display_name or plugin_root.name,
    )

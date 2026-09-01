from __future__ import annotations

import ast
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol

from application.plugins.catalog import _set_plugin_enabled


class PluginInstallProgress(Protocol):
    """Progress dependency used by the plugin installation action."""

    def update(self, **changes: Any) -> None: ...

    def append_log(self, line: str) -> None: ...


class PluginPackageDependencyInstallError(RuntimeError):
    code = "package_dependency_failed"
    fallback_allowed = False
    user_message = "包体已通过校验，但依赖安装失败，请查看日志。"

    def __init__(self, detail: str) -> None:
        super().__init__(self.user_message)
        self.detail = detail.strip() or self.user_message


def _repo_slug_from_source(source: str) -> str:
    from plugin_system.registry.download import normalize_repo_slug

    return normalize_repo_slug(source)


def _is_repo_source(source: str) -> bool:
    raw = source.strip().lower()
    if ":" in source and not (
        raw.startswith("http://")
        or raw.startswith("https://")
        or raw.startswith("git@github.com:")
    ):
        return False
    return bool(_repo_slug_from_source(source))


def _lookup_registry_plugin(source: str) -> Any | None:
    repo_slug = _repo_slug_from_source(source).lower()
    source_key = source.strip().lower()
    try:
        from plugin_system.registry.catalog import fetch_registry_plugins
        from plugin_system.registry.download import normalize_repo_slug
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
        if str(getattr(rec, "id", "") or "").strip().lower() == source_key:
            return rec
        if rec.name.strip().lower() == source_key:
            return rec
        if str(getattr(rec, "display_name", "") or "").strip().lower() == source_key:
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
    from plugin_system.host import (
        append_plugin_manifest_entry_if_missing,
        normalize_manifest_entry,
    )

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


def _has_registry_package(record: Any | None) -> bool:
    if record is None:
        return False
    import os

    if os.environ.get("SHINSEKAI_PLUGIN_DISABLE_PACKAGE_INSTALL") == "1":
        return False
    package_url = str(
        getattr(record, "package_url", "") or getattr(record, "download_url", "") or ""
    ).strip()
    package_sha256 = str(
        getattr(record, "package_sha256", "") or getattr(record, "sha256", "") or ""
    ).strip()
    return bool(package_url and package_sha256)


def _registry_package_metadata(
    record: Any,
    *,
    dependency_status: str = "",
    dependency_detail: str = "",
    package_status: str = "verified",
) -> dict[str, Any]:
    package_source = str(getattr(record, "package_source", "") or "r2").strip()
    package_url = str(
        getattr(record, "package_url", "") or getattr(record, "download_url", "") or ""
    ).strip()
    package_sha256 = str(
        getattr(record, "package_sha256", "") or getattr(record, "sha256", "") or ""
    ).strip()
    package_size = getattr(record, "package_size", None)
    if package_size is None:
        package_size = getattr(record, "size", None)
    is_verified_package = package_status == "verified"
    metadata: dict[str, Any] = {
        "dependencyDetail": dependency_detail,
        "dependencyStatus": dependency_status,
        "entry": str(getattr(record, "entry", "") or "").strip(),
        "packageSource": package_source if is_verified_package else "local",
        "packageStatus": package_status,
        "repo": str(getattr(record, "repo", "") or "").strip(),
        "sourceLabel": "官方包体 (R2)" if is_verified_package else "已有插件目录",
        "sourceType": "package" if is_verified_package else "existing",
    }
    if is_verified_package:
        metadata.update(
            {
                "packageSha256": package_sha256,
                "packageSize": package_size,
                "packageUrl": package_url,
            }
        )
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _with_install_metadata(
    result: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, Any]:
    out = dict(result)
    out["install"] = dict(metadata)
    return out


def _package_error_details(exc: BaseException) -> dict[str, Any]:
    from plugin_system.install.package import PluginPackageError

    current: BaseException | None = exc
    while current is not None:
        code = getattr(current, "code", "")
        user_message = getattr(current, "user_message", "")
        if isinstance(current, PluginPackageError) or code or user_message:
            detail = str(
                getattr(current, "detail", "") or current or current.__class__.__name__
            )
            out: dict[str, Any] = {
                "detail": detail,
                "errorCode": str(code or "plugin_package_error"),
                "errorUserMessage": str(user_message or detail),
                "fallbackAllowed": bool(getattr(current, "fallback_allowed", False)),
            }
            status_code = getattr(current, "status_code", None)
            if status_code is not None:
                out["httpStatus"] = status_code
            return out
        current = current.__cause__
    detail = str(exc) or exc.__class__.__name__
    return {
        "detail": detail,
        "errorCode": "plugin_install_error",
        "errorUserMessage": detail,
        "fallbackAllowed": False,
    }


def _package_error_allows_github_fallback(exc: BaseException) -> bool:
    from plugin_system.install.package import (
        PluginPackageNetworkError,
        PluginPackageNonFallbackError,
    )

    current: BaseException | None = exc
    saw_network_error = False
    while current is not None:
        if isinstance(current, PluginPackageNonFallbackError):
            return False
        if isinstance(current, PluginPackageNetworkError):
            saw_network_error = True
        current = current.__cause__
    return saw_network_error


def _update_task_package_error(
    progress: PluginInstallProgress,
    details: dict[str, Any],
) -> None:
    updates = {
        "errorCode": details.get("errorCode", ""),
        "errorDetail": details.get("detail", ""),
        "errorUserMessage": details.get("errorUserMessage", ""),
        "fallbackAllowed": bool(details.get("fallbackAllowed")),
    }
    if details.get("httpStatus") is not None:
        updates["httpStatus"] = details["httpStatus"]
    progress.update(**updates)


def _restore_package_target(
    target: Path, backup: Path | None, *, remove_new_target: bool
) -> None:
    if remove_new_target and target.exists():
        shutil.rmtree(target, ignore_errors=True)
    if backup is not None and backup.exists() and not target.exists():
        backup.rename(target)


def _install_registry_package_source(
    progress: PluginInstallProgress,
    record: Any,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    from plugin_system.install.package import (
        install_registry_package_under_plugins,
        registry_package_target,
    )
    from plugin_system.requirements.install import install_plugin_requirements_txt
    from plugin_system.registry.download import (
        mark_repo_downloaded,
        normalize_repo_slug,
    )

    repo_slug = normalize_repo_slug(str(getattr(record, "repo", "") or ""))
    entry = str(getattr(record, "entry", "") or "").strip()
    display_name = str(
        getattr(record, "display_name", "") or getattr(record, "name", "") or ""
    ).strip()
    description = str(getattr(record, "description", "") or "").strip()
    target = registry_package_target(record, plugins_parent=Path("plugins"))
    existed_before = target.is_dir()
    backup: Path | None = None
    if overwrite and existed_before:
        backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
        target.rename(backup)

    progress.update(
        message=f"正在下载 {display_name or repo_slug or target.name} 的官方包体。",
        phase="download",
        progress=0.12,
        installSource="package",
        installSourceLabel="官方包体 (R2)",
        packageStatus="downloading",
    )

    def _pip_line(line: str) -> None:
        progress.append_log(line)

    dependency_status = ""
    dependency_detail = ""
    try:
        package_status = "existing" if existed_before and not overwrite else "verified"
        plugin_root = install_registry_package_under_plugins(
            record,
            overwrite=overwrite,
            plugins_parent=Path("plugins"),
        )
        package_message = (
            "检测到已有插件目录，跳过官方包体校验。"
            if package_status == "existing"
            else "官方包体已校验，正在安装插件依赖。"
        )
        progress.update(
            message=package_message,
            phase="pip",
            progress=0.72,
            packageStatus=package_status,
        )
        dependency_status, dependency_detail = install_plugin_requirements_txt(
            plugin_root, on_output_line=_pip_line
        )
        if dependency_detail:
            progress.append_log(dependency_detail)
        if dependency_status in {
            "pip_failed",
            "pip_timeout",
            "pip_exception",
            "pip_conflict",
        }:
            dependency_error = PluginPackageDependencyInstallError(
                dependency_detail or dependency_status
            )
            error_message = dependency_error.user_message
            progress.update(
                errorCode=dependency_error.code,
                errorDetail=dependency_error.detail,
                errorUserMessage=error_message,
                fallbackAllowed=dependency_error.fallback_allowed,
            )
            raise dependency_error
        if not entry:
            entry = _infer_plugin_entry(plugin_root)
        metadata = _registry_package_metadata(
            record,
            dependency_status=dependency_status,
            dependency_detail=dependency_detail,
            package_status=package_status,
        )
        if entry:
            metadata["entry"] = entry
        progress.update(
            message="正在登记官方包体安装状态。",
            phase="manifest",
            progress=0.9,
            dependencyInstallStatus=dependency_status,
        )
        if entry:
            result = _plugin_result_from_manifest(entry)
            if repo_slug:
                mark_repo_downloaded(
                    repo_slug, manifest_entry=entry, install_metadata=metadata
                )
            progress.update(message="官方包体安装完成。", phase="completed", progress=1)
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
            return _with_install_metadata(result, metadata)
        if repo_slug:
            mark_repo_downloaded(repo_slug, manifest_entry=None)
        result = _synthetic_plugin_result(
            description=description
            or f"包体已下载到 {plugin_root.as_posix()}，但没有找到可登记的插件入口。",
            enabled=False,
            plugin_id=repo_slug or str(getattr(record, "id", "") or target.name),
            title=display_name or target.name,
        )
        progress.update(
            message="官方包体已下载，但没有找到可登记的插件入口。", progress=1
        )
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return _with_install_metadata(result, metadata)
    except Exception:
        _restore_package_target(
            target, backup, remove_new_target=(not existed_before or backup is not None)
        )
        progress.update(packageStatus="failed")
        raise


def install_plugin(
    progress: PluginInstallProgress,
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

    registry_rec = _lookup_registry_plugin(source)
    if ref_kind == "latest" and _has_registry_package(registry_rec):
        try:
            return _install_registry_package_source(
                progress, registry_rec, overwrite=overwrite
            )
        except Exception as exc:
            repo = str(getattr(registry_rec, "repo", "") or "").strip()
            if repo and _package_error_allows_github_fallback(exc):
                details = _package_error_details(exc)
                fallback_message = str(
                    details.get("errorUserMessage")
                    or "官方包体暂时无法访问，正在自动尝试 GitHub 源码安装。"
                )
                progress.update(
                    errorCode=details.get("errorCode", ""),
                    errorDetail=details.get("detail", ""),
                    errorUserMessage=fallback_message,
                    fallbackAllowed=True,
                    message=fallback_message,
                    notice=fallback_message,
                    noticeKind="info",
                    phase="download",
                    installSource="github",
                    packageStatus="fallback",
                )
                progress.append_log(f"{fallback_message} {details.get('detail', exc)}")
                return _install_github_plugin_source(
                    progress,
                    repo,
                    ref_kind=ref_kind,
                    tag_name=tag_name,
                    overwrite=overwrite,
                )
            details = _package_error_details(exc)
            _update_task_package_error(progress, details)
            message = str(
                details.get("errorUserMessage") or details.get("detail") or exc
            )
            progress.append_log(f"{message} {details.get('detail', '')}".strip())
            raise RuntimeError(message) from exc

    if not _is_repo_source(source) and registry_rec is not None:
        repo = str(getattr(registry_rec, "repo", "") or "").strip()
        if repo:
            return _install_github_plugin_source(
                progress,
                repo,
                ref_kind=ref_kind,
                tag_name=tag_name,
                overwrite=overwrite,
            )

    return _install_github_plugin_source(
        progress,
        source,
        ref_kind=ref_kind,
        tag_name=tag_name,
        overwrite=overwrite,
    )


def _install_github_plugin_source(
    progress: PluginInstallProgress,
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
        progress.update(
            message="正在写入插件清单。",
            phase="manifest",
            progress=0.45,
        )
        result = _plugin_result_from_manifest(source)
        progress.update(message="插件清单已更新。", progress=0.9)
        return result

    from plugin_system.update.github import install_github_plugin_under_plugins
    from plugin_system.requirements.install import install_plugin_requirements_txt
    from plugin_system.registry.download import (
        format_download_error,
        mark_repo_downloaded,
        normalize_repo_slug,
    )

    repo_slug = normalize_repo_slug(_repo_slug_from_source(source))
    progress.update(
        message="正在查询插件索引。",
        phase="registry",
        progress=0.04,
    )
    registry_rec = _lookup_registry_plugin(repo_slug)
    entry = str(getattr(registry_rec, "entry", "") or "").strip()
    display_name = str(getattr(registry_rec, "name", "") or "").strip()
    description = str(getattr(registry_rec, "description", "") or "").strip()

    progress.update(
        message=f"正在下载 {repo_slug}。",
        phase="download",
        progress=0.08,
    )

    def _progress(current: int, total: int | None) -> None:
        if total:
            ratio = min(max(current / total, 0), 1)
            download_progress = 0.08 + ratio * 0.55
            message = f"正在下载 {current}/{total} bytes。"
        else:
            download_progress = 0.18
            message = f"已下载 {current} bytes。"
        progress.update(
            message=message,
            phase="download",
            progress=round(download_progress, 4),
        )

    def _phase(phase: str) -> None:
        if phase == "extract":
            progress.update(
                message="正在解压插件源码。", phase="extract", progress=0.66
            )

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

    progress.update(
        message="正在检查并安装插件 requirements.txt。",
        phase="pip",
        progress=0.72,
    )

    def _pip_line(line: str) -> None:
        progress.append_log(line)

    pip_code, pip_detail = install_plugin_requirements_txt(
        plugin_root, on_output_line=_pip_line
    )
    if pip_code in {"pip_failed", "pip_timeout", "pip_exception", "pip_conflict"}:
        detail = pip_detail or pip_code
        raise RuntimeError(f"插件依赖安装失败：{detail}")

    if not entry:
        entry = _infer_plugin_entry(plugin_root)

    progress.update(message="正在登记插件安装状态。", phase="manifest", progress=0.9)
    mark_repo_downloaded(repo_slug, manifest_entry=entry or None)
    if entry:
        return _plugin_result_from_manifest(entry)

    return _synthetic_plugin_result(
        description=description
        or f"源码已下载到 {plugin_root.as_posix()}，但未找到 manifest entry。",
        enabled=False,
        plugin_id=repo_slug,
        title=display_name or plugin_root.name,
    )

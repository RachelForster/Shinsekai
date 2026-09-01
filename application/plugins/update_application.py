"""Update the host application from its configured source repository."""

from __future__ import annotations

from typing import Any

from application.runtime.state import BridgeState
from application.runtime.tasks import _append_task_log, _update_task


def get_application_update_info() -> dict[str, Any]:
    from core.app_update.github_bundle import (
        default_app_github_repo_slug,
        read_local_version,
        resolve_project_root,
    )

    return {
        "repo": default_app_github_repo_slug(),
        "version": read_local_version(resolve_project_root()).strip(),
    }


def list_application_update_tags() -> dict[str, Any]:
    from core.app_update.github_bundle import (
        default_app_github_repo_slug,
        fetch_recent_tag_names,
    )

    slug = default_app_github_repo_slug().strip()
    if not slug or slug.count("/") < 1:
        raise ValueError("无法解析主程序 GitHub 仓库。")
    return {"tags": fetch_recent_tag_names(slug)}


def list_plugin_repository_tags(payload: dict[str, Any]) -> dict[str, Any]:
    from core.app_update.github_bundle import fetch_recent_tag_names
    from plugin_system.registry.download import normalize_repo_slug

    slug = normalize_repo_slug(str(payload.get("repo") or ""))
    if not slug or slug.count("/") < 1:
        raise ValueError("repo is required")
    return {"tags": fetch_recent_tag_names(slug)}


def update_application(
    state: BridgeState,
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    from core.app_update.github_bundle import (
        default_app_github_repo_slug,
        overwrite_merge_app_tree,
        read_local_version,
        resolve_project_root,
    )
    from plugin_system.requirements.install import install_plugin_requirements_txt
    from plugin_system.registry.download import format_download_error

    slug = default_app_github_repo_slug().strip()
    if not slug or slug.count("/") < 1:
        raise ValueError("无法解析主程序 GitHub 仓库。")
    ref_kind = str(payload.get("refKind") or "latest").strip()
    if ref_kind not in {"latest", "head", "tag"}:
        ref_kind = "latest"
    tag_name = str(payload.get("tagName") or "").strip()
    if ref_kind == "tag" and not tag_name:
        raise ValueError("请选择一个有效的 tag。")

    _update_task(
        state,
        task_id,
        message=f"正在下载 {slug} 源码归档。",
        phase="download",
        progress=0.05,
    )

    def report_download(current: int, total: int | None) -> None:
        if total:
            ratio = min(max(current / total, 0), 1)
            progress = 0.05 + ratio * 0.58
            message = f"正在下载 {current}/{total} bytes。"
        else:
            progress = 0.2
            message = f"已下载 {current} bytes。"
        _update_task(
            state,
            task_id,
            message=message,
            phase="download",
            progress=round(progress, 4),
        )

    def report_phase(phase: str) -> None:
        if phase == "extract":
            _update_task(
                state,
                task_id,
                message="正在合并到程序目录。",
                phase="merge",
                progress=0.68,
            )

    try:
        merge_result = overwrite_merge_app_tree(
            slug,
            ref_kind,  # type: ignore[arg-type]
            tag_name,
            progress=report_download,
            on_phase=report_phase,
        )
    except Exception as exc:
        raise RuntimeError(format_download_error(exc)) from exc

    _update_task(
        state,
        task_id,
        message="正在检查主程序 requirements.txt。",
        phase="pip",
        progress=0.88,
    )

    def append_pip_log(line: str) -> None:
        _append_task_log(state, task_id, line)

    pip_code, detail = install_plugin_requirements_txt(
        resolve_project_root(),
        on_output_line=append_pip_log,
    )
    if detail:
        _append_task_log(state, task_id, detail)
    _update_task(
        state,
        task_id,
        message="正在检查主程序 requirements-runtime-core.txt。",
        phase="pip",
        progress=0.92,
    )
    runtime_pip_code, runtime_detail = install_plugin_requirements_txt(
        resolve_project_root(),
        requirements_file="requirements-runtime-core.txt",
        on_output_line=append_pip_log,
    )
    if runtime_detail:
        _append_task_log(
            state,
            task_id,
            f"requirements-runtime-core.txt: {runtime_detail}",
        )
    detail = "\n".join(
        item
        for item in (
            detail,
            f"requirements-runtime-core.txt: {runtime_detail}"
            if runtime_detail
            else "",
        )
        if item
    )
    pip_code = (
        f"requirements.txt:{pip_code};requirements-runtime-core.txt:{runtime_pip_code}"
    )
    version = read_local_version(resolve_project_root()).strip()
    result = {
        "detail": detail,
        "frontendDistUpdated": bool(merge_result.get("frontendDistUpdated")),
        "message": "文件已合并到当前目录。建议关闭本程序后重新启动以使代码生效。",
        "pipCode": pip_code,
        "version": version,
    }
    _update_task(
        state,
        task_id,
        message=result["message"],
        phase="completed",
        progress=1,
        result=result,
    )
    return result

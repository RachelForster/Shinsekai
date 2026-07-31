from __future__ import annotations

from pathlib import Path
from typing import Any

from sdk.path_contract import resolve_runtime_asset_read_path


DEFAULT_T2I_PROVIDER = "comfyui"
DEFAULT_T2I_API_URL = "http://127.0.0.1:8188"
T2I_WORKFLOW_RESOURCE_PREFIXES = (
    ("assets", "system", "workflow"),
    ("assets", "workflows"),
)


def validate_t2i_paths_for_save(config: Any, *, project_root: Path) -> None:
    """Validate the persisted T2I paths against the runtime's exact read contract.

    The default empty ComfyUI configuration means that image generation is
    intentionally skipped.  Once any ComfyUI setting opts into the feature, the
    workflow must be a readable regular file.  The work directory remains
    optional because an already-running local or remote ComfyUI server does not
    need to be launched by Shinsekai.
    """

    provider = str(getattr(config, "t2i_provider", DEFAULT_T2I_PROVIDER) or "").strip()
    provider_key = provider.lower() or DEFAULT_T2I_PROVIDER
    if provider_key != DEFAULT_T2I_PROVIDER:
        return

    api_url = str(getattr(config, "t2i_api_url", DEFAULT_T2I_API_URL) or "").strip()
    workflow_path = str(getattr(config, "t2i_default_workflow_path", "") or "")
    work_path = str(getattr(config, "t2i_work_path", "") or "")
    is_skipped_default = (
        not workflow_path
        and not work_path
        and api_url.lower() in {"", DEFAULT_T2I_API_URL}
    )
    if is_skipped_default:
        return

    if not workflow_path:
        raise ValueError("启用 ComfyUI 时需要填写默认工作流文件。")
    workflow = resolve_runtime_asset_read_path(
        workflow_path,
        root=project_root,
        resource_prefixes=T2I_WORKFLOW_RESOURCE_PREFIXES,
    )
    if not workflow.is_file():
        raise ValueError("ComfyUI 默认工作流必须是已存在的文件。")

    if work_path:
        work_directory = resolve_runtime_asset_read_path(
            work_path,
            root=project_root,
            resource_prefixes=(),
        )
        if not work_directory.is_dir():
            raise ValueError("ComfyUI 工作目录必须是已存在的目录。")

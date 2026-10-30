"""Open the bundled T2I workflows in the host file manager."""

from pathlib import Path

from core.media.file_operations import open_local_path
from sdk.path_utils import safe_project_path


def open_t2i_workflow_folder(project_root: Path) -> dict[str, str]:
    folder = safe_project_path("ai/t2i/workflows", root=project_root)
    if not folder.is_dir():
        raise FileNotFoundError(f"工作流文件夹不存在：{folder}")
    result = open_local_path(str(folder))
    if "error" in result:
        raise RuntimeError(f"无法打开工作流文件夹 {folder}：{result['error']}")
    return {"path": folder.as_posix()}

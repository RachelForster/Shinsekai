"""PyInstaller 冻结为无控制台（windowed）时，将 print / logging / traceback 重定向到发行根下日志文件。"""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from core.file_transactions import open_text_append_without_links
from core.paths import (
    managed_child_path,
    managed_project_storage,
    project_root,
    safe_path_component_with_suffix,
)


def _should_redirect_stdio_to_file() -> bool:
    """无控制台/非终端输出时（--noconsole 打包）才重定向，保留 --build-with-console 的黑框。"""
    o = sys.stdout
    if o is None:
        return True
    isatty = getattr(o, "isatty", None)
    if isatty is None:
        return True
    try:
        return not isatty()
    except (OSError, ValueError, AttributeError):
        return True


def _frozen_log_filename(log_name: str) -> str:
    safe = "".join(c for c in log_name if c.isalnum() or c in "._-") or "app"
    try:
        return safe_path_component_with_suffix(
            safe,
            ".log",
            field="frozen log filename",
        )
    except ValueError:
        return safe_path_component_with_suffix(
            f"app-{safe}",
            ".log",
            field="frozen log filename",
        )


def init_frozen_stdio(log_name: str) -> None:
    """
    在 sys.frozen 为 True 且当前 stdout 非 TTY 时，把 stdout/stderr 指到
    <发行根>/logs/<log_name>.log，并为尚未迁移到统一 logging 的旧入口保留 basicConfig。
    """
    if (
        not getattr(sys, "frozen", False)
        or not _should_redirect_stdio_to_file()
        or not isinstance(log_name, str)
        or not log_name
    ):
        return
    root = project_root()
    d = managed_project_storage("logs", root=root)
    d.mkdir(parents=True, exist_ok=True)
    path = managed_child_path(
        d,
        _frozen_log_filename(log_name),
        field="frozen log filename",
    )
    f = open_text_append_without_links(path)
    f.write(
        f"\n{'=' * 60}\n{datetime.now().isoformat(sep=' ', timespec='seconds')}  {log_name}  \n"
    )
    f.flush()
    sys.stdout = f
    sys.stderr = f
    root_l = logging.getLogger()
    if not root_l.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

"""PyInstaller 冻结为无控制台（windowed）时，将 print / logging / traceback 重定向到发行根下日志文件。"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


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


def init_frozen_stdio(log_name: str) -> None:
    """
    在 sys.frozen 为 True 且当前 stdout 非 TTY 时，把 stdout/stderr 指到
    <发行根>/logs/<log_name>.log，并若根 logger 尚无处理器则 basicConfig（与现有 logging 用法兼容）。
    """
    if (
        not getattr(sys, "frozen", False)
        or not _should_redirect_stdio_to_file()
        or not isinstance(log_name, str)
        or not log_name
    ):
        return
    safe = "".join(c for c in log_name if c.isalnum() or c in "._-")
    if not safe:
        safe = "app"
    rel = os.environ.get("EASYAI_PROJECT_ROOT")
    root = Path(rel).resolve() if rel else Path(sys.executable).resolve().parent.parent
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{safe}.log"
    f = path.open("a", encoding="utf-8", buffering=1)
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

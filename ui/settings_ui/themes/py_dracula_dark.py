"""从同目录的 `py_dracula_dark.qss` 加载全局样式表字符串。"""

from __future__ import annotations

from pathlib import Path

_QSS = Path(__file__).with_name("py_dracula_dark.qss")


def load_pydracula_dark() -> str:
    if not _QSS.is_file():
        return ""
    return _QSS.read_text(encoding="utf-8")

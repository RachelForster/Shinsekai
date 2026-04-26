"""PyDracula 风格 QSS（基于 Wanderson M. PyDracula 主题，经裁剪与去资源化）。"""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load_pydracula_dark() -> str:
    """返回 py_dracula_dark.qss 全文。"""
    p = _DIR / "py_dracula_dark.qss"
    return p.read_text(encoding="utf-8")

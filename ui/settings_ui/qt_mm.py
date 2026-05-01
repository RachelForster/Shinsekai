"""
PySide6 多媒体：惰性导入。MERGE/部分冻结环境下模块可能只在先打的包内，顶层 from …QtMultimedia
会在 import 时崩溃，故统一在此 try，失败时返回 None。
"""

from __future__ import annotations

from typing import Any, Type

def try_load() -> tuple[Type[Any] | None, Type[Any] | None]:
    """成功则返回 (QMediaPlayer, QAudioOutput)；否则 (None, None)。"""
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError, OSError):
        return None, None
    return QMediaPlayer, QAudioOutput


def try_create_pair(parent: Any) -> tuple[Any, Any] | tuple[None, None]:
    """在 parent 上创建播放器与输出；无 QtMultimedia 时返回 (None, None)。"""
    QMP, QAO = try_load()
    if QMP is None or QAO is None:
        return None, None
    p = QMP(parent)
    a = QAO(parent)
    p.setAudioOutput(a)
    return p, a

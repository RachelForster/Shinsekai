"""
轻量性能计时 — 追踪一段流程的耗时。

用法::

    from sdk.logging import stopwatch

    with stopwatch("TTS synthesis"):
        audio = tts.generate(text)

    # 输出: [stopwatch] TTS synthesis 3.214s

    @stopwatch("LLM call")
    def chat(messages):
        ...
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import ContextDecorator
from typing import Any

from sdk.logging.api import get_logger

_log = get_logger(__name__)


class stopwatch(ContextDecorator):
    """上下文管理器 + 装饰器，记录代码块执行时长。

    ``threshold``（秒）仅在超过该值时输出；``logger`` 可指定目标 logger。
    """

    __slots__ = ("_name", "_threshold", "_logger", "_start")

    def __init__(
        self,
        name: str,
        *,
        threshold: float = 0.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._name = name
        self._threshold = float(threshold)
        self._logger = logger or _log
        self._start: float = 0.0

    def __enter__(self) -> stopwatch:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        elapsed = time.perf_counter() - self._start
        if elapsed >= self._threshold:
            self._logger.info("[stopwatch] %s  %.3fs", self._name, elapsed)

    def __repr__(self) -> str:
        return f"stopwatch({self._name!r})"

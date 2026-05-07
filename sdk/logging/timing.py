"""
非侵入式跨线程性能计时器。

同线程（上下文管理器）::

    from sdk.logging.timing import tracker
    with tracker.track("TTS synthesis"):
        audio = tts.generate(text)

跨线程（start_cross / stop_cross）::

    tracker.start_cross("e2e")   # 线程 A — 记下当前时间
    ...
    tracker.stop_cross("e2e")    # 线程 B — 计算耗时并累加

打印报告::

    tracker.print_report()
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Dict, Optional, Tuple

_log = logging.getLogger("stopwatch")


class TimingTracker:
    """全局单例，跨线程时间段累加统计。"""

    _instance: Optional[TimingTracker] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._data_lock = threading.Lock()
        self._stats: Dict[str, Tuple[float, int]] = {}
        self._pending: Dict[str, float] = {}   # 跨线程 start_cross → stop_cross
        self._local = threading.local()         # 同线程 track / start / stop

    @contextmanager
    def track(self, name: str):
        """同线程上下文管理器。"""
        self.start(name)
        try:
            yield
        finally:
            self.stop(name)

    def start(self, name: str) -> None:
        """同线程开始计时（与 stop 配对，必须在同一线程）。"""
        self._local.start = time.perf_counter()

    def stop(self, name: str) -> None:
        """同线程结束计时。"""
        t0 = getattr(self._local, "start", None)
        if t0 is None:
            return
        self._local.start = None
        self._commit(name, t0)

    def start_cross(self, name: str) -> None:
        """跨线程开始计时（可在不同线程调用 stop_cross）。"""
        with self._data_lock:
            self._pending[name] = time.perf_counter()

    def stop_cross(self, name: str) -> None:
        """跨线程结束计时。"""
        with self._data_lock:
            t0 = self._pending.pop(name, None)
        if t0 is None:
            return
        self._commit(name, t0)

    def _commit(self, name: str, t0: float) -> None:
        elapsed = time.perf_counter() - t0
        _log.info("[stopwatch] %s  %.3fs", name, elapsed)
        with self._data_lock:
            total, cnt = self._stats.get(name, (0.0, 0))
            self._stats[name] = (total + elapsed, cnt + 1)

    def get_stats(self) -> Dict[str, Dict[str, float]]:
        with self._data_lock:
            return {
                name: {
                    "total_sec": total,
                    "count": cnt,
                    "avg_sec": total / cnt if cnt else 0.0,
                }
                for name, (total, cnt) in self._stats.items()
            }

    def print_report(self) -> None:
        stats = self.get_stats()
        if not stats:
            print("No timing data collected.")
            return
        print("\n=== Timing Report ===")
        items = sorted(stats.items(), key=lambda x: x[1]["total_sec"], reverse=True)
        for name, data in items:
            print(
                f"  {name}: total={data['total_sec']:.3f}s  "
                f"count={data['count']}  avg={data['avg_sec'] * 1000:.1f}ms"
            )

    def reset(self) -> None:
        with self._data_lock:
            self._stats.clear()
            self._pending.clear()


tracker = TimingTracker()

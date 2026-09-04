"""Shared thread-backed DAG worker base and compatibility helpers."""

import threading

from config.config_manager import ConfigManager
from sdk.graph import DagNode

from ..context import try_get_app_runtime


class ThreadDagNode(DagNode):
    """Each DAG node owns one standard-library worker thread."""

    def __init__(self, name: str, parent=None) -> None:
        del parent
        super().__init__(name)
        self.running = True
        self._thread: threading.Thread | None = None

    def isRunning(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout_ms: int = 3000) -> bool:
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(max(0, timeout_ms) / 1000)
        return not thread.is_alive()

    def start(self) -> None:
        if self.isRunning():
            return
        self.running = True
        self._thread = threading.Thread(
            target=self.run,
            name=f"shinsekai-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止线程并等待退出（最多 3 秒）。"""
        self.running = False
        if not self.wait(3000):
            print(
                f"警告: {type(self).__name__} 线程未在 3 秒内退出，请检查阻塞中的外部调用"
            )


def getCharacter(name: str):
    rt = try_get_app_runtime()
    if rt is not None:
        return rt.config.get_character_by_name(name)
    return ConfigManager().get_character_by_name(name)

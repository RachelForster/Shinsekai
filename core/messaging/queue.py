"""Queue primitives used by the chat message pipeline."""

from __future__ import annotations

from queue import Queue
from typing import List, Optional


class ClearableQueue(Queue):
    """A queue that can atomically discard pending, not in-flight, items."""

    def clear(self) -> None:
        with self.mutex:
            count = len(self.queue)
            self.queue.clear()
            self.unfinished_tasks = max(0, self.unfinished_tasks - count)
            if self.unfinished_tasks == 0:
                self.all_tasks_done.notify_all()
            self.not_full.notify_all()

    def drain(self, max_items: Optional[int] = None) -> List[object]:
        """Return and account for up to ``max_items`` pending FIFO items."""
        result: List[object] = []
        with self.mutex:
            while self.queue and (max_items is None or len(result) < max_items):
                result.append(self.queue.popleft())
            if result:
                self.unfinished_tasks = max(0, self.unfinished_tasks - len(result))
                if self.unfinished_tasks == 0:
                    self.all_tasks_done.notify_all()
                self.not_full.notify_all()
        return result

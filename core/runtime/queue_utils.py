"""Queue utilities for the runtime."""

from __future__ import annotations

from queue import Queue
from typing import List, Optional


class ClearableQueue(Queue):
    """A Queue subclass with a thread-safe **clear()** and **drain()**.

    Uses the same internal mutex as :meth:`get` / :meth:`put`, so clearing is
    safe even when another thread may be blocked on ``get()``.  After a clear,
    ``unfinished_tasks`` is reset to 0 so that :meth:`join` returns immediately.
    """

    def clear(self) -> None:
        """Remove **all** items from the queue.

        Decrements ``unfinished_tasks`` for each item that was still sitting in
        the queue — items already retrieved via :meth:`get` (in-flight) still
        belong to their workers and will be :meth:`task_done`'d separately.
        """
        with self.mutex:
            count = len(self.queue)
            self.queue.clear()
            self.unfinished_tasks = max(0, self.unfinished_tasks - count)
            if self.unfinished_tasks == 0:
                self.all_tasks_done.notify_all()
            self.not_full.notify_all()
            self.not_empty.notify_all()  # unblock any waiting get()

    def drain(self, max_items: Optional[int] = None) -> List[object]:
        """Drain up to *max_items* from the queue **without blocking**.

        Returns the drained items so callers can inspect or log them.
        If *max_items* is ``None``, drains everything currently in the queue.
        """
        result: List[object] = []
        with self.mutex:
            count = 0
            while self.queue and (max_items is None or count < max_items):
                result.append(self.queue.popleft())
                count += 1
            if result:
                self.unfinished_tasks = max(0, self.unfinished_tasks - len(result))
                if self.unfinished_tasks == 0:
                    self.all_tasks_done.notify_all()
                self.not_full.notify_all()
        return result

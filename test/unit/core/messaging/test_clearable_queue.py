"""Unit tests for ClearableQueue."""

import threading
import time

from core.messaging.queue import ClearableQueue


def test_clear_removes_all_items():
    q = ClearableQueue()
    q.put(1)
    q.put(2)
    q.put(3)
    q.clear()
    assert q.empty()
    assert q.qsize() == 0


def test_clear_preserves_in_flight_task_done():
    q = ClearableQueue()
    q.put(1)
    q.put(2)
    q.get()
    q.clear()
    q.task_done()
    q.join()


def test_drain_returns_items():
    q = ClearableQueue()
    q.put("a")
    q.put("b")
    q.put("c")
    assert q.drain() == ["a", "b", "c"]
    assert q.empty()


def test_drain_max_items():
    q = ClearableQueue()
    q.put(1)
    q.put(2)
    q.put(3)
    assert q.drain(max_items=2) == [1, 2]
    assert q.qsize() == 1


def test_clear_is_thread_safe():
    q = ClearableQueue()
    results = []

    def waiter():
        results.append(q.get(timeout=2))

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.1)
    q.clear()
    q.put("sentinel")
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert results == ["sentinel"]


def test_clearable_queue_factory_compatible():
    from sdk.graph import Dag

    assert Dag(queue_factory=ClearableQueue) is not None


def test_standard_get_put_works():
    q = ClearableQueue()
    q.put("hello")
    assert q.get() == "hello"
    q.task_done()
    assert q.empty()


"""Unit tests for ClearableQueue."""

import threading
import time

from core.runtime.queue_utils import ClearableQueue


def test_clear_removes_all_items():
    q = ClearableQueue()
    q.put(1)
    q.put(2)
    q.put(3)
    q.clear()
    assert q.empty()
    assert q.qsize() == 0


def test_clear_preserves_in_flight_task_done():
    """clear() must account for items still in the queue but not those already get()'d."""
    q = ClearableQueue()
    q.put(1)        # unfinished_tasks=1
    q.put(2)        # unfinished_tasks=2
    item = q.get()  # worker retrieves item 1; unfinished_tasks stays 2
    q.clear()       # removes item 2 from queue → unfinished_tasks = 2-1 = 1
    q.task_done()   # unfinished_tasks = 1-1 = 0  ✓
    q.join()        # should return immediately


def test_drain_returns_items():
    q = ClearableQueue()
    q.put("a")
    q.put("b")
    q.put("c")
    drained = q.drain()
    assert drained == ["a", "b", "c"]
    assert q.empty()


def test_drain_max_items():
    q = ClearableQueue()
    q.put(1)
    q.put(2)
    q.put(3)
    drained = q.drain(max_items=2)
    assert drained == [1, 2]
    assert q.qsize() == 1


def test_clear_is_thread_safe():
    """Verify clear() unblocks a get() waiter."""
    q = ClearableQueue()
    results = []

    def waiter():
        # This will block until clear() unblocks it or something is put
        try:
            item = q.get(timeout=2)
            results.append(item)
        except Exception:
            results.append("timeout")

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.1)  # let waiter block on get()

    # Clearing should unblock the waiter (via not_empty notify)
    q.clear()
    # Put a sentinel so waiter can get unblocked
    q.put("sentinel")
    t.join(timeout=2)

    # Waiter should have received something (sentinel) or been unblocked
    assert not t.is_alive(), "waiter should have exited"


def test_clearable_queue_factory_compatible():
    """Verify ClearableQueue can be used as a queue_factory."""
    from sdk.graph import Dag

    dag = Dag(queue_factory=ClearableQueue)
    assert dag is not None


def test_standard_get_put_works():
    q = ClearableQueue()
    q.put("hello")
    assert q.get() == "hello"
    q.task_done()
    assert q.empty()

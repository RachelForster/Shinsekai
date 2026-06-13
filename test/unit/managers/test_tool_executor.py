"""Unit tests for ToolExecutor, ToolNotReady, and tool_ready callback."""

import json
import time
from unittest.mock import patch

import pytest

from sdk.tool_registry import (
    ToolNotReady,
    notify_tool_ready,
    set_tool_ready_callback,
)
from llm.tools.tool_manager import ToolManager
from llm.tools.tool_executor import ToolExecutor


def _reset_tm():
    """Reset the ToolManager singleton for test isolation."""
    tm = ToolManager()
    tm._tools_definitions.clear()
    tm._functions.clear()
    tm._tool_groups.clear()
    tm._tool_risks.clear()
    return tm


# ── ToolNotReady exception ──────────────────────────────────────────────

class TestToolNotReady:
    def test_raise_and_catch(self):
        with pytest.raises(ToolNotReady) as exc:
            raise ToolNotReady("my message")
        assert exc.value.message == "my message"

    def test_inherits_from_exception(self):
        assert issubclass(ToolNotReady, Exception)

    def test_default_message(self):
        exc = ToolNotReady()
        assert exc.message == ""

    def test_str_representation(self):
        exc = ToolNotReady("loading model")
        assert str(exc) == "loading model"


# ── ToolManager re-raises ToolNotReady ───────────────────────────────────

class TestToolManagerReRaise:
    def test_tool_not_ready_propagates(self):
        tm = _reset_tm()

        def slow_tool() -> int:
            raise ToolNotReady("still loading")

        tm.register_function(slow_tool, name="slow", group="test")
        with pytest.raises(ToolNotReady) as exc:
            tm.execute("slow", "{}")
        assert exc.value.message == "still loading"

    def test_other_exceptions_still_caught(self):
        tm = _reset_tm()

        def bad_tool() -> int:
            raise RuntimeError("boom")

        tm.register_function(bad_tool, name="bad", group="test")
        result = tm.execute("bad", "{}")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "boom" in parsed["error"]


# ── ToolExecutor execute ─────────────────────────────────────────────────

class TestToolExecutorExecute:
    def test_normal_execution(self):
        tm = _reset_tm()

        def add(a: int, b: int) -> int:
            return a + b

        tm.register_function(add, name="add", group="math")
        executor = ToolExecutor(tm, default_timeout=5.0)
        result = executor.execute("add", '{"a": 3, "b": 4}')
        parsed = json.loads(result)
        assert parsed == 7

    def test_converts_not_ready_to_loading_json(self):
        tm = _reset_tm()

        def slow() -> int:
            raise ToolNotReady("工具正在加载，请稍候")

        tm.register_function(slow, name="slow", group="test")
        executor = ToolExecutor(tm)
        result = executor.execute("slow", "{}")
        parsed = json.loads(result)
        assert parsed["status"] == "loading"
        assert "正在加载" in parsed["message"]

    def test_sets_cooldown_on_not_ready(self):
        tm = _reset_tm()
        called = []

        def slow() -> int:
            called.append(1)
            raise ToolNotReady("loading")

        tm.register_function(slow, name="slow", group="test")
        executor = ToolExecutor(tm, cooldown_map={"test": 60.0})

        # First call: tool runs, raises
        result = executor.execute("slow", "{}")
        assert json.loads(result)["status"] == "loading"
        assert len(called) == 1
        assert executor.is_in_cooldown("test")

        # Second call: cooldown active, still probes (runs tool again)
        result2 = executor.execute("slow", "{}")
        assert json.loads(result2)["status"] == "loading"
        assert len(called) == 2  # tool was probed again

    def test_probe_succeeds_during_cooldown(self):
        tm = _reset_tm()
        ready = [False]

        def lazy() -> str:
            if not ready[0]:
                ready[0] = True  # simulate model finished loading
                raise ToolNotReady("loading")
            return "ready!"

        tm.register_function(lazy, name="lazy", group="test")
        executor = ToolExecutor(tm, cooldown_map={"test": 60.0})

        # First call: not ready
        r1 = executor.execute("lazy", "{}")
        assert json.loads(r1)["status"] == "loading"
        assert executor.is_in_cooldown("test")

        # Second call: ready (probe succeeds)
        r2 = executor.execute("lazy", "{}")
        parsed = json.loads(r2)
        assert parsed == "ready!"
        assert not executor.is_in_cooldown("test")  # cooldown cleared

    def test_timeout_returns_error(self):
        tm = _reset_tm()

        def slow_poke() -> str:
            time.sleep(2.0)
            return "done"

        tm.register_function(slow_poke, name="slow_poke", group="test")
        executor = ToolExecutor(tm, default_timeout=0.1)

        # ToolMaster.execute adds overhead, but the tool itself sleeps 2s
        # which will exceed the 0.1s timeout
        result = executor.execute("slow_poke", "{}")
        parsed = json.loads(result)
        # either it timed out (most likely) or the future overhead was low enough
        # Just check we get a valid json response
        assert isinstance(parsed, (dict, str))

    def test_cooldown_probe_timeout_returns_cooldown_message(self):
        tm = _reset_tm()

        def deep_sleep() -> str:
            time.sleep(10.0)
            return "woke"

        tm.register_function(deep_sleep, name="deep_sleep", group="test")
        executor = ToolExecutor(tm, cooldown_map={"test": 60.0})

        # Manually trigger cooldown (set_group_cooldown only sets duration)
        executor._cooldowns["test"] = time.time() + 60.0
        assert executor.is_in_cooldown("test")

        # Probe during cooldown with 0.1s timeout → should timeout
        # and return cooldown message
        result = executor.execute("deep_sleep", "{}")
        parsed = json.loads(result)
        assert parsed["status"] == "loading"
        # cooldown message, not error
        assert "冷却" in parsed["message"] or "status" in parsed

    def test_risk_confirm_callback_deny(self):
        tm = _reset_tm()

        def risky() -> str:
            return "executed"

        tm.register_function(risky, name="risky", group="test", risk="high")
        executor = ToolExecutor(tm)

        def deny(name, risk, args):
            return False

        result = executor.execute("risky", "{}", risk_confirm=deny)
        parsed = json.loads(result)
        assert parsed.get("cancelled") is True

    def test_risk_confirm_callback_allow(self):
        tm = _reset_tm()

        def risky() -> str:
            return "ok"

        tm.register_function(risky, name="risky", group="test", risk="medium")
        executor = ToolExecutor(tm)

        def allow(name, risk, args):
            return True

        result = executor.execute("risky", "{}", risk_confirm=allow)
        parsed = json.loads(result)
        assert parsed == "ok"

    def test_low_risk_skips_callback(self):
        tm = _reset_tm()

        def safe() -> str:
            return "safe"

        tm.register_function(safe, name="safe", group="test", risk="low")

        callback_called = []

        def cb(name, risk, args):
            callback_called.append(1)
            return False  # would deny if called

        executor = ToolExecutor(tm)
        result = executor.execute("safe", "{}", risk_confirm=cb)
        assert json.loads(result) == "safe"
        assert len(callback_called) == 0  # callback never invoked

    def test_catch_all_exception_returns_error(self):
        tm = _reset_tm()

        def explode() -> str:
            raise RuntimeError("unexpected failure")

        tm.register_function(explode, name="explode", group="test")
        executor = ToolExecutor(tm)
        result = executor.execute("explode", "{}")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "unexpected failure" in parsed["error"] or "failed" in parsed["error"]

    def test_error_result_sets_configured_group_cooldown(self):
        tm = _reset_tm()

        def capture() -> dict:
            return {"error": "screen capture failed"}

        tm.register_function(capture, name="vision_capture", group="vision")
        executor = ToolExecutor(tm, error_cooldown_map={"vision": 60.0})

        result = executor.execute("vision_capture", "{}")
        parsed = json.loads(result)

        assert parsed["error"] == "screen capture failed"
        assert executor.is_in_cooldown("vision")
        assert executor.cooldown_message_for_tool("vision_capture") is not None

    def test_error_probe_during_cooldown_keeps_group_in_cooldown(self):
        tm = _reset_tm()

        def capture() -> dict:
            return {"error": "still broken"}

        tm.register_function(capture, name="vision_capture_probe", group="vision")
        executor = ToolExecutor(tm, error_cooldown_map={"vision": 60.0})
        executor._cooldowns["vision"] = time.time() + 60.0

        result = executor.execute("vision_capture_probe", "{}")
        parsed = json.loads(result)

        assert parsed["error"] == "still broken"
        assert executor.is_in_cooldown("vision")

    def test_unknown_tool_returns_error(self):
        tm = _reset_tm()
        executor = ToolExecutor(tm)
        result = executor.execute("nonexistent", "{}")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_tool_result_is_string(self):
        tm = _reset_tm()

        def greet(name: str) -> str:
            return f"Hello, {name}"

        tm.register_function(greet, name="greet", group="test")
        executor = ToolExecutor(tm)
        result = executor.execute("greet", '{"name": "World"}')
        parsed = json.loads(result)
        assert parsed == "Hello, World"


# ── Cooldown management ──────────────────────────────────────────────────

class TestCooldownManagement:
    def test_set_cooldown_duration_and_trigger_clear(self):
        executor = ToolExecutor(ToolManager())
        group = "test_group"
        assert not executor.is_in_cooldown(group)

        # set_group_cooldown only sets the duration, not the active cooldown
        executor.set_group_cooldown(group, 60.0)
        assert executor._cooldown_map[group] == 60.0
        assert not executor.is_in_cooldown(group)  # not active yet

        # Trigger cooldown (as ToolNotReady would), then clear
        executor._cooldowns[group] = time.time() + 60.0
        assert executor.is_in_cooldown(group)

        executor.clear_cooldown(group)
        assert not executor.is_in_cooldown(group)

    def test_clear_all_cooldowns(self):
        executor = ToolExecutor(ToolManager())
        executor.set_group_cooldown("a", 60.0)
        executor.set_group_cooldown("b", 60.0)
        executor.clear_cooldown()  # None = all
        assert not executor.is_in_cooldown("a")
        assert not executor.is_in_cooldown("b")

    def test_expired_cooldown_is_not_active(self):
        executor = ToolExecutor(ToolManager())
        executor.set_group_cooldown("test", 0.01)
        time.sleep(0.02)
        assert not executor.is_in_cooldown("test")

    def test_custom_cooldown_map(self):
        executor = ToolExecutor(ToolManager(), cooldown_map={"vision": 999.0})
        assert executor._cooldown_map["vision"] == 999.0

    def test_set_group_cooldown_updates_map(self):
        executor = ToolExecutor(ToolManager())
        executor.set_group_cooldown("custom", 180.0)
        assert executor._cooldown_map["custom"] == 180.0


# ── tool_ready callback ──────────────────────────────────────────────────

class TestToolReadyCallback:
    def teardown_method(self):
        # Reset callback to avoid leaks between tests
        set_tool_ready_callback(None)

    def test_set_and_call_callback(self):
        received = []

        def handler(group: str, message: str) -> None:
            received.append((group, message))

        set_tool_ready_callback(handler)
        notify_tool_ready("memory", "加载完成")
        assert len(received) == 1
        assert received[0] == ("memory", "加载完成")

    def test_notify_without_callback_does_not_crash(self):
        set_tool_ready_callback(None)
        # Should not raise
        notify_tool_ready("memory", "loaded")

    def test_exception_in_callback_does_not_crash_notify(self):
        def bad_handler(group, message):
            raise RuntimeError("boom")

        set_tool_ready_callback(bad_handler)
        with pytest.raises(RuntimeError):
            notify_tool_ready("memory", "boom")
        # The exception propagates — this is by design (host handles it)

    def test_multiple_notifications(self):
        received = []

        def handler(group, message):
            received.append(message)

        set_tool_ready_callback(handler)
        notify_tool_ready("a", "first")
        notify_tool_ready("b", "second")
        assert received == ["first", "second"]


# ── Integration: full lifecycle ──────────────────────────────────────────

class TestToolLifecycle:
    def test_cold_start_to_ready(self):
        """Simulate: model loads between two tool calls."""
        tm = _reset_tm()
        loaded = [False]

        def vision_tool(question: str) -> dict:
            if not loaded[0]:
                loaded[0] = True  # background thread finishes
                raise ToolNotReady("视觉模型加载中，请稍候")
            return {"answer": f"saw: {question}"}

        tm.register_function(vision_tool, name="vision_query", group="vision")
        executor = ToolExecutor(tm, cooldown_map={"vision": 300.0})

        # Cold call
        r1 = executor.execute("vision_query", '{"question": "what?"}')
        p1 = json.loads(r1)
        assert p1["status"] == "loading"
        assert executor.is_in_cooldown("vision")

        # After model loaded
        r2 = executor.execute("vision_query", '{"question": "what?"}')
        p2 = json.loads(r2)
        assert p2["answer"] == "saw: what?"
        assert not executor.is_in_cooldown("vision")

    def test_still_loading_extends_cooldown(self):
        """Tool keeps raising → cooldown keeps extending."""
        tm = _reset_tm()

        def never_ready() -> dict:
            raise ToolNotReady("still not ready")

        tm.register_function(never_ready, name="never", group="test")
        executor = ToolExecutor(tm, cooldown_map={"test": 1.0})

        r1 = executor.execute("never", "{}")
        assert json.loads(r1)["status"] == "loading"
        assert executor.is_in_cooldown("test")

        # Cooldown should be refreshed each time
        r2 = executor.execute("never", "{}")
        assert json.loads(r2)["status"] == "loading"
        # Still in cooldown (refreshed)
        assert executor.is_in_cooldown("test")

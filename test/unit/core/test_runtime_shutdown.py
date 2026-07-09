import unittest

from core.runtime.shutdown import shutdown_chat_runtime
from sdk.hooks import clear_shutdown_hooks, register_shutdown_hook


class _WorkflowStub:
    def __init__(self, calls):
        self._calls = calls

    def stop(self):
        self._calls.append("workflow_stop")


class RuntimeShutdownTests(unittest.TestCase):
    def tearDown(self):
        clear_shutdown_hooks()

    def test_shutdown_runs_steps_in_expected_order(self):
        calls = []
        workflow = _WorkflowStub(calls)
        register_shutdown_hook(lambda: calls.append("memory_shutdown"), label="memory_shutdown")

        shutdown_chat_runtime(
            workflow=workflow,
            plugin_shutdown=lambda: calls.append("plugin_shutdown"),
            tts_shutdown=lambda: calls.append("tts_shutdown"),
            save_history=lambda: calls.append("save_history"),
            save_background=lambda: calls.append("save_background"),
            emit_session_closed=lambda: calls.append("emit_session_closed"),
            close_stream_sink=lambda: calls.append("close_stream_sink"),
        )

        self.assertEqual(
            calls,
            [
                "emit_session_closed",
                "workflow_stop",
                "memory_shutdown",
                "plugin_shutdown",
                "tts_shutdown",
                "save_history",
                "save_background",
                "close_stream_sink",
            ],
        )

    def test_shutdown_continues_after_failure_and_reports_errors(self):
        calls = []
        errors = []
        workflow = _WorkflowStub(calls)
        register_shutdown_hook(lambda: calls.append("memory_shutdown"), label="memory_shutdown")

        def broken_plugin_shutdown():
            calls.append("plugin_shutdown")
            raise RuntimeError("boom")

        result = shutdown_chat_runtime(
            workflow=workflow,
            plugin_shutdown=broken_plugin_shutdown,
            tts_shutdown=lambda: calls.append("tts_shutdown"),
            save_history=lambda: calls.append("save_history"),
            save_background=lambda: calls.append("save_background"),
            emit_session_closed=lambda: calls.append("emit_session_closed"),
            close_stream_sink=lambda: calls.append("close_stream_sink"),
            on_error=lambda step, exc: errors.append((step, str(exc))),
        )

        self.assertEqual(
            calls,
            [
                "emit_session_closed",
                "workflow_stop",
                "memory_shutdown",
                "plugin_shutdown",
                "tts_shutdown",
                "save_history",
                "save_background",
                "close_stream_sink",
            ],
        )
        self.assertEqual(errors, [("plugin_shutdown", "boom")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "plugin_shutdown")
        self.assertEqual(str(result[0][1]), "boom")

    def test_registered_shutdown_hook_failure_is_reported_and_does_not_stop_later_steps(self):
        calls = []
        errors = []

        def broken_memory_shutdown():
            calls.append("memory_shutdown")
            raise RuntimeError("memory boom")

        register_shutdown_hook(broken_memory_shutdown, label="memory_shutdown")

        result = shutdown_chat_runtime(
            plugin_shutdown=lambda: calls.append("plugin_shutdown"),
            on_error=lambda step, exc: errors.append((step, str(exc))),
        )

        self.assertEqual(calls, ["memory_shutdown", "plugin_shutdown"])
        self.assertEqual(errors, [("memory_shutdown", "memory boom")])
        self.assertEqual(result[0][0], "memory_shutdown")

    def test_shutdown_hook_unregister_removes_step(self):
        calls = []
        unregister = register_shutdown_hook(lambda: calls.append("removed"), label="removed")
        register_shutdown_hook(lambda: calls.append("kept"), label="kept")

        unregister()
        shutdown_chat_runtime()

        self.assertEqual(calls, ["kept"])


if __name__ == "__main__":
    unittest.main()

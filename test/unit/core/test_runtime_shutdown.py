import unittest

from core.runtime.shutdown import shutdown_chat_runtime


class _WorkflowStub:
    def __init__(self, calls):
        self._calls = calls

    def stop(self):
        self._calls.append("workflow_stop")


class RuntimeShutdownTests(unittest.TestCase):
    def test_shutdown_runs_steps_in_expected_order(self):
        calls = []
        workflow = _WorkflowStub(calls)

        shutdown_chat_runtime(
            workflow=workflow,
            memory_shutdown=lambda: calls.append("memory_shutdown"),
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

        def broken_plugin_shutdown():
            calls.append("plugin_shutdown")
            raise RuntimeError("boom")

        result = shutdown_chat_runtime(
            workflow=workflow,
            memory_shutdown=lambda: calls.append("memory_shutdown"),
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def shutdown_chat_runtime(
    *,
    workflow: Any | None = None,
    memory_shutdown: Callable[[], None] | None = None,
    plugin_shutdown: Callable[[], None] | None = None,
    tts_shutdown: Callable[[], None] | None = None,
    save_history: Callable[[], None] | None = None,
    save_background: Callable[[], None] | None = None,
    emit_session_closed: Callable[[], None] | None = None,
    close_stream_sink: Callable[[], None] | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[tuple[str, Exception]]:
    """Run chat runtime shutdown steps in a resilient, testable sequence.

    Each step is attempted even if an earlier one fails. Callers may provide an
    ``on_error`` hook for logging.
    """

    steps: list[tuple[str, Callable[[], None]]] = []
    if emit_session_closed is not None:
        steps.append(("emit_session_closed", emit_session_closed))
    if workflow is not None and hasattr(workflow, "stop"):
        steps.append(("workflow_stop", workflow.stop))
    if memory_shutdown is not None:
        steps.append(("memory_shutdown", memory_shutdown))
    if plugin_shutdown is not None:
        steps.append(("plugin_shutdown", plugin_shutdown))
    if tts_shutdown is not None:
        steps.append(("tts_shutdown", tts_shutdown))
    if save_history is not None:
        steps.append(("save_history", save_history))
    if save_background is not None:
        steps.append(("save_background", save_background))
    if close_stream_sink is not None:
        steps.append(("close_stream_sink", close_stream_sink))

    errors: list[tuple[str, Exception]] = []
    for name, action in steps:
        try:
            action()
        except Exception as exc:
            errors.append((name, exc))
            if on_error is not None:
                on_error(name, exc)
    return errors

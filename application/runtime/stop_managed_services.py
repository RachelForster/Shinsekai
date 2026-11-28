"""Unified Bridge host shutdown use case for all managed background services."""

from __future__ import annotations

import logging
import threading
from typing import Any

from sdk.process_guard import get_process_registry

logger = logging.getLogger(__name__)
_SHUTDOWN_LOCK = threading.Lock()


def stop_managed_services(
    state: Any | None = None,
    *,
    reason: str = "shutdown",
    chat_wait_timeout: float = 4.0,
    process_wait_timeout: float = 3.0,
) -> dict[str, Any]:
    """Stop active chat, agent, perception, and all host-managed servers."""
    errors: list[dict[str, str]] = []
    stopped_count = 0

    def _run_step(name: str, action: Any) -> Any:
        try:
            return action()
        except Exception as exc:
            logger.warning(
                "Managed service shutdown step failed (%s): %s",
                name,
                exc,
                exc_info=True,
            )
            errors.append({"step": name, "error": str(exc)})
            return None

    with _SHUTDOWN_LOCK:
        def _stop_chat() -> None:
            from application.chat.composition import shutdown_active_chat_process
            from application.chat.stop_chat import stop_chat

            has_session = bool(
                state is not None
                and str((getattr(state, "chat_session", {}) or {}).get("sessionId") or "").strip()
            )
            if has_session:
                stop_chat(state, reason=reason, wait_timeout=chat_wait_timeout)
            shutdown_active_chat_process(wait_timeout=min(2.0, max(0.5, chat_wait_timeout)))

        def _stop_agent() -> None:
            services = getattr(state, "services", None)
            close_runtimes = getattr(services, "close_runtimes", None)
            if callable(close_runtimes):
                close_runtimes()

        def _stop_perception() -> None:
            from application.perception.server_launcher import (
                shutdown_perception_local_server,
            )

            shutdown_perception_local_server()

        _run_step("chat", _stop_chat)
        _run_step("agent", _stop_agent)
        _run_step("perception", _stop_perception)
        result = _run_step(
            "process_registry",
            lambda: get_process_registry().shutdown_host_all(timeout=process_wait_timeout),
        )
        if isinstance(result, int):
            stopped_count = result

    return {
        "ok": True,
        "stoppedProcesses": stopped_count,
        "errors": errors,
    }

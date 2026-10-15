"""Knowledge warm-up, cancellation, and degradation for chat startup."""

from __future__ import annotations

import logging
import time

from sdk.chat_init import InitChatCancelled, InitChatContext

logger = logging.getLogger(__name__)


def prepare_knowledge(
    context: InitChatContext,
    *,
    knowledge_status_func,
    timeout: float = 600.0,
    poll_interval: float = 0.45,
    sleep_func=time.sleep,
    monotonic_func=time.monotonic,
) -> bool:
    """Return whether retrieval is ready; cancellation always aborts startup."""
    try:
        return _wait_for_knowledge(
            context, knowledge_status_func=knowledge_status_func, timeout=timeout,
            poll_interval=poll_interval, sleep_func=sleep_func, monotonic_func=monotonic_func,
        )
    except InitChatCancelled:
        raise
    except Exception as exc:
        context.raise_if_cancelled()
        logger.warning("Knowledge warm-up failed; continuing without retrieval: %s", exc)
        context.report(
            1.0, "Knowledge is unavailable; continuing without knowledge.",
            phase="knowledge.degraded", log=f"Knowledge warm-up failed: {exc}",
        )
        return False


def _wait_for_knowledge(
    context, *, knowledge_status_func, timeout, poll_interval, sleep_func, monotonic_func,
) -> bool:
    deadline = monotonic_func() + max(0.01, float(timeout))
    start_loading = True
    forwarded_log_count = 0
    while True:
        context.raise_if_cancelled()
        result = knowledge_status_func(start_loading=start_loading)
        start_loading = False
        context.raise_if_cancelled()
        if result is None:
            context.report(
                1.0, "Knowledge service is unavailable; continuing without knowledge.",
                phase="knowledge",
                log="Knowledge warm-up skipped because no bridge knowledge service is configured.",
            )
            return False
        if not isinstance(result, dict):
            raise RuntimeError("knowledge service returned an invalid status response")
        task = result.get("task")
        if isinstance(task, dict):
            task_logs = [str(line) for line in (task.get("logs") or []) if str(line).strip()]
            if forwarded_log_count > len(task_logs):
                forwarded_log_count = 0
            new_logs = task_logs[forwarded_log_count:]
            forwarded_log_count = len(task_logs)
            try:
                progress = None if task.get("progress") is None else float(task["progress"])
            except (TypeError, ValueError):
                progress = None
            context.report(
                progress,
                str(task.get("message") or result.get("message") or "Loading knowledge."),
                phase=f"knowledge.{str(task.get('phase') or 'loading')}",
                logs=new_logs,
            )
        status = str(result.get("status") or "").strip().lower()
        if status == "ready":
            context.report(1.0, "Knowledge is ready.", phase="knowledge")
            return True
        if status in {"loading", "not_started"}:
            if monotonic_func() >= deadline:
                raise TimeoutError("knowledge initialization timed out")
            sleep_func(min(max(0.01, float(poll_interval)), max(0.0, deadline - monotonic_func())))
            continue
        if status == "missing_dependency":
            module_name = str(result.get("moduleName") or "mem0")
            raise RuntimeError(f"Knowledge dependency is unavailable: {module_name}.")
        error = str(
            result.get("errorUserMessage") or result.get("message") or result.get("error") or ""
        ).strip()
        raise RuntimeError(error or f"unexpected knowledge service status: {status or 'unknown'}")

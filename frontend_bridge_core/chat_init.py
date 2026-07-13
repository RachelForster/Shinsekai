from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .chat import (
    _chat_process_running,
    _chat_runtime_closing,
    _chat_runtime_mode,
    _chat_snapshot,
    _chat_stream_initial_snapshot,
    _close_chat,
)
from .state import BridgeState
from .tasks import (
    TaskCancelled,
    _create_task,
    _get_task,
    _is_running_task,
    _is_task_cancel_requested,
    _run_background_task,
    _update_task,
)

CHAT_INIT_TIMEOUT_SECONDS = 15 * 60.0
CHAT_INIT_POLL_INTERVAL_SECONDS = 0.12

_TASK_TEXT_FIELDS = (
    "errorCode",
    "errorDetail",
    "errorUserMessage",
    "message",
    "notice",
    "noticeKind",
    "phase",
)


class ChatInitFailed(RuntimeError):
    pass


def _chat_init_lock(state: BridgeState) -> threading.Lock:
    lock = getattr(state, "chat_init_lock", None)
    if lock is None:
        lock = threading.Lock()
        state.chat_init_lock = lock
    return lock


def _safe_task_changes(raw_task: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field in _TASK_TEXT_FIELDS:
        if field in raw_task:
            changes[field] = str(raw_task.get(field) or "")[:4000]

    if "httpStatus" in raw_task:
        value = raw_task.get("httpStatus")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            changes["httpStatus"] = int(value)

    if "progress" in raw_task:
        progress = raw_task.get("progress")
        if progress is None:
            changes["progress"] = None
        elif isinstance(progress, (int, float)) and not isinstance(progress, bool):
            changes["progress"] = max(0.0, min(1.0, float(progress)))

    logs = raw_task.get("logs")
    if isinstance(logs, list):
        changes["logs"] = [str(line)[:4000] for line in logs[-120:] if str(line).strip()]
    return changes


def _terminal_error(task: dict[str, Any], fallback: str) -> str:
    for field in ("errorUserMessage", "error", "message"):
        value = str(task.get(field) or "").strip()
        if value:
            return value
    return fallback


def _clear_chat_session_id(state: BridgeState, session_id: str) -> None:
    if str(state.chat_session.get("sessionId") or "") != session_id:
        return
    state.chat_session = {**state.chat_session, "sessionId": ""}


def _cleanup_chat_init(state: BridgeState, session_id: str, *, reason: str) -> None:
    try:
        _close_chat(state, reason=reason)
    except Exception:
        pass
    finally:
        chat_stream = getattr(state, "chat_stream", None)
        if chat_stream is not None:
            try:
                chat_stream.delete_session(session_id)
            except Exception:
                pass
        _clear_chat_session_id(state, session_id)


def _run_chat_init(
    state: BridgeState,
    task_id: str,
    launch: Callable[[dict[str, str]], dict[str, Any]],
    *,
    timeout: float,
) -> dict[str, Any]:
    if _chat_runtime_closing(state):
        raise RuntimeError("chat runtime is closing; try again shortly")
    # Preserve the legacy behavior for an already-running, fully initialized
    # runtime. The async API simply resolves to its current snapshot.
    if _chat_process_running():
        return _chat_snapshot(state)

    chat_stream = getattr(state, "chat_stream", None)
    if chat_stream is None:
        raise RuntimeError("chat stream service is unavailable")

    stream_info = chat_stream.create_session(_chat_stream_initial_snapshot(_chat_snapshot(state, "idle", "")))
    session_id = str(stream_info.get("sessionId") or "").strip()
    if not session_id:
        raise RuntimeError("failed to create chat initialization session")

    keep_session = _chat_runtime_mode(state) == "react"
    try:
        if _is_task_cancel_requested(state, task_id):
            raise TaskCancelled()
        _update_task(
            state,
            task_id,
            message="Starting chat runtime.",
            phase="launching",
            progress=0.02,
        )
        launch_result = launch(stream_info)
        if not isinstance(launch_result, dict):
            raise RuntimeError("chat launch returned an invalid result")
        if str(launch_result.get("status") or "") == "error" and isinstance(
            launch_result.get("runtimeDependencyError"),
            dict,
        ):
            # A missing runtime dependency is an expected, actionable result.
            # Keep the task successful so the frontend can open its existing
            # dependency-install confirmation flow from the returned snapshot.
            launch_result.pop("_chatInitStreamAttached", None)
            chat_stream.delete_session(session_id)
            _clear_chat_session_id(state, session_id)
            return launch_result
        if str(launch_result.get("status") or "") == "error":
            raise ChatInitFailed(
                str(launch_result.get("statusMessage") or launch_result.get("dialogText") or "chat launch failed")
            )

        # A concurrent legacy launch can win between the initial process check
        # and the launch callback. In that case no init stream was attached and
        # the existing runtime is already the authoritative result.
        if not bool(launch_result.pop("_chatInitStreamAttached", False)):
            if _chat_process_running():
                chat_stream.delete_session(session_id)
                return _chat_snapshot(state)
            raise ChatInitFailed("chat runtime did not attach its initialization stream")

        deadline = time.monotonic() + max(float(timeout), 0.1)
        last_changes: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if _is_task_cancel_requested(state, task_id):
                raise TaskCancelled()

            snapshot = chat_stream.get_snapshot(session_id)
            init_task = snapshot.get("initTask") if isinstance(snapshot, dict) else None
            if isinstance(init_task, dict):
                changes = _safe_task_changes(init_task)
                if changes and changes != last_changes:
                    _update_task(state, task_id, **changes)
                    last_changes = changes

                status = str(init_task.get("status") or "").strip().lower()
                if status == "succeeded":
                    if not keep_session:
                        chat_stream.delete_session(session_id)
                    return _chat_snapshot(state)
                if status == "failed":
                    raise ChatInitFailed(_terminal_error(init_task, "chat initialization failed"))
                if status == "cancelled":
                    raise TaskCancelled()

            if not _chat_process_running():
                detail = init_task if isinstance(init_task, dict) else {}
                raise ChatInitFailed(_terminal_error(detail, "chat process exited before initialization completed"))
            time.sleep(CHAT_INIT_POLL_INTERVAL_SECONDS)

        raise TimeoutError(f"chat initialization timed out after {int(max(float(timeout), 0.1))} seconds")
    except BaseException:
        _cleanup_chat_init(state, session_id, reason="Chat initialization did not complete.")
        raise


def start_chat_init(
    state: BridgeState,
    *,
    mode: str,
    launch: Callable[[dict[str, str]], dict[str, Any]],
    timeout: float = CHAT_INIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"launch", "resume-last"}:
        raise ValueError("mode must be 'launch' or 'resume-last'")

    lock = _chat_init_lock(state)
    with lock:
        active_id = str(getattr(state, "chat_init_task_id", "") or "").strip()
        if active_id:
            try:
                active_task = _get_task(state, active_id)
            except KeyError:
                active_task = None
            if active_task is not None and _is_running_task(active_task):
                return active_task
            state.chat_init_task_id = ""

        task = _create_task(
            state,
            kind="chat-init",
            title="Initialize chat",
            message="Preparing chat runtime.",
        )
        task_id = str(task["id"])
        state.chat_init_task_id = task_id

    def _run() -> None:
        try:
            _run_background_task(
                state,
                task_id,
                lambda: _run_chat_init(state, task_id, launch, timeout=timeout),
            )
        finally:
            with lock:
                if str(getattr(state, "chat_init_task_id", "") or "") == task_id:
                    state.chat_init_task_id = ""

    threading.Thread(target=_run, name=f"chat-init-{task_id[:8]}", daemon=True).start()
    return _get_task(state, task_id)

from frontend_bridge_core.state import BridgeState, plugin_load_snapshot, set_plugin_load_status
from frontend_bridge_core.tasks import (
    TaskCancelled,
    _append_task_log,
    _create_task,
    _get_task,
    _is_running_task,
    _is_task_cancel_requested,
    _request_task_cancel,
    _run_background_task,
    _update_task,
)


def _state() -> BridgeState:
    return BridgeState(
        background_manager=None,
        character_manager=None,
        config_manager=None,
        template_generator=None,
    )


def test_task_lifecycle_tracks_successful_background_work():
    state = _state()
    task = _create_task(state, kind="demo", title="Demo", message="Queued")

    assert task["status"] == "queued"
    assert task["phase"] == "queued"
    assert _is_running_task(task)

    updated = _update_task(state, task["id"], message="Running", progress=0.4)
    assert updated["message"] == "Running"
    assert updated["progress"] == 0.4

    _run_background_task(state, task["id"], lambda: {"ok": True})

    finished = _get_task(state, task["id"])
    assert finished["status"] == "succeeded"
    assert finished["phase"] == "completed"
    assert finished["progress"] == 1
    assert finished["result"] == {"ok": True}
    assert not _is_running_task(finished)


def test_task_cancel_request_only_changes_running_tasks():
    state = _state()
    task = _create_task(state, kind="download", title="Download")

    cancelling = _request_task_cancel(state, task["id"])

    assert cancelling["cancelRequested"] is True
    assert cancelling["phase"] == "cancelling"
    assert _is_task_cancel_requested(state, task["id"]) is True

    _update_task(state, task["id"], status="succeeded", phase="completed")
    unchanged = _request_task_cancel(state, task["id"])

    assert unchanged["phase"] == "completed"
    assert unchanged["status"] == "succeeded"


def test_background_task_records_cancelled_and_failed_states():
    state = _state()
    cancelled = _create_task(state, kind="download", title="Download")
    failed = _create_task(state, kind="download", title="Download")

    def cancel_worker():
        raise TaskCancelled()

    def fail_worker():
        raise RuntimeError("boom")

    _run_background_task(state, cancelled["id"], cancel_worker)
    _run_background_task(state, failed["id"], fail_worker)

    cancelled_task = _get_task(state, cancelled["id"])
    failed_task = _get_task(state, failed["id"])
    assert cancelled_task["status"] == "cancelled"
    assert cancelled_task["phase"] == "cancelled"
    assert cancelled_task["progress"] is None
    assert failed_task["status"] == "failed"
    assert failed_task["phase"] == "failed"
    assert failed_task["error"] == "boom"


def test_plugin_load_status_snapshot_tracks_completion():
    state = _state()

    set_plugin_load_status(state, "loading")
    loading = plugin_load_snapshot(state)

    assert loading["status"] == "loading"
    assert loading["startedAt"] > 0
    assert loading["completedAt"] == 0

    set_plugin_load_status(state, "ready")
    ready = plugin_load_snapshot(state)

    assert ready["status"] == "ready"
    assert ready["completedAt"] >= ready["startedAt"]
    assert ready["elapsedSec"] >= 0


def test_task_logs_are_trimmed_and_ignore_blank_lines():
    state = _state()
    task = _create_task(state, kind="demo", title="Demo")

    _append_task_log(state, task["id"], "  ")
    for index in range(5):
        _append_task_log(state, task["id"], f"line {index}", limit=3)

    stored = _get_task(state, task["id"])
    assert stored["logs"] == ["line 2", "line 3", "line 4"]

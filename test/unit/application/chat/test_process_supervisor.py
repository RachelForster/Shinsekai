"""Lifecycle and resource ownership contracts independent of bridge or subprocesses."""

from __future__ import annotations

import io
from dataclasses import FrozenInstanceError
from threading import Event, Lock, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.chat import composition as chat
from application.chat.host.process_supervisor import ChatProcessSupervisor
from application.chat.host.ports import (
    LaunchPlan,
    LaunchRejected,
    MemoryProcessResources,
)
from sdk.chat_process import ChatProcessEvent as Phase
from sdk.hooks import PluginHookDispatcher
from test.unit.application.chat.runtime_process_fakes import (
    FakeChild,
    launch_arguments,
    make_state,
)


@pytest.fixture
def supervisor(tmp_path):
    child = FakeChild(["timeout", 0])
    resources = MemoryProcessResources(lock=Lock())
    events = []
    popen = MagicMock(return_value=child)

    def stop(process, **_kwargs):
        process.wait(timeout=0)

    value = ChatProcessSupervisor(
        system=SimpleNamespace(popen=popen),
        log_path=lambda: tmp_path / "chat.log",
        hidden_kwargs=lambda: {},
        stop_child=stop,
        wait_exit=lambda process, timeout: process.wait(timeout=timeout) == 0,
        monotonic=lambda: 10,
        failed_launch=lambda code, _path: f"exit {code}",
        resources=resources,
        publish=events.append,
    )
    value.fixture_child = child
    value.fixture_events = events
    value.fixture_popen = popen
    value.fixture_plan = LaunchPlan(
        ["python", "main.py"], tmp_path, {"secret": "private"}
    )
    yield value
    value.close_log()


def launch(supervisor):
    return supervisor.launch(
        lambda: supervisor.fixture_plan, session_id="fixture-session"
    )


def test_successful_lifecycle_notifies_after_owned_resources_are_released(supervisor):
    observed = []

    def observe(context):
        assert supervisor.resources.lock.acquire(blocking=False)
        supervisor.resources.lock.release()
        observed.append((context, supervisor.running(), supervisor.resources.log))

    supervisor.publish = observe
    assert "已启动" in launch(supervisor)
    handle = supervisor.resources.log
    supervisor.shutdown()
    assert [item[0].event for item in observed] == [
        Phase.STARTING,
        Phase.STARTED,
        Phase.STOPPING,
        Phase.STOPPED,
    ]
    assert [item[1] for item in observed] == [False, True, True, False]
    assert all(item[0].session_id == "fixture-session" for item in observed)
    assert observed[-1][0].exit_code == 0
    assert observed[-1][2] is None
    assert handle.closed
    assert supervisor.resources.process is None
    assert "secret" not in repr(observed[1][0])
    with pytest.raises(FrozenInstanceError):
        observed[1][0].pid = 1


def test_duplicate_launch_skips_preparation_and_hooks(supervisor):
    launch(supervisor)
    prepare = MagicMock()
    assert "已经在运行" in supervisor.launch(prepare)
    prepare.assert_not_called()
    assert len(supervisor.fixture_events) == 2
    supervisor.fixture_popen.assert_called_once()


@pytest.mark.parametrize("exit_code,phase", [(0, Phase.STOPPED), (7, Phase.FAILED)])
def test_exit_after_start_is_reported_once_and_releases_owned_log(
    supervisor, exit_code, phase
):
    launch(supervisor)
    context = supervisor.fixture_events[0]
    assert context.launch_id
    handle = supervisor.resources.log
    supervisor.fixture_child.poll = lambda: exit_code
    assert not supervisor.running()
    assert not supervisor.running()
    supervisor.shutdown()
    assert [event.event for event in supervisor.fixture_events] == [
        Phase.STARTING,
        Phase.STARTED,
        phase,
    ]
    terminal = supervisor.fixture_events[-1]
    assert terminal.launch_id == context.launch_id
    assert terminal.session_id == "fixture-session"
    assert terminal.exit_code == exit_code
    assert handle.closed
    assert supervisor.resources.process is None


def test_stale_exit_cannot_release_replacement_process_or_its_log(supervisor):
    launch(supervisor)
    original = supervisor.fixture_child
    context = supervisor.fixture_events[-1]
    replacement, handle = FakeChild(), io.StringIO()
    supervisor.resources.process = replacement
    supervisor.resources.log = handle
    original.running = False
    supervisor.observe_exit(original, context)
    assert supervisor.resources.process is replacement
    assert supervisor.resources.log is handle
    assert not handle.closed
    assert len(supervisor.fixture_events) == 2


def test_relaunch_detects_old_exit_before_discarding_its_identity(supervisor):
    launch(supervisor)
    previous_id = supervisor.fixture_events[0].launch_id
    supervisor.fixture_child.running = False
    replacement = FakeChild(["timeout", 0])
    supervisor.fixture_popen.return_value = replacement
    launch(supervisor)
    assert [event.event for event in supervisor.fixture_events] == [
        Phase.STARTING,
        Phase.STARTED,
        Phase.STOPPED,
        Phase.STARTING,
        Phase.STARTED,
    ]
    assert supervisor.fixture_events[2].launch_id == previous_id
    assert supervisor.fixture_events[3].launch_id != previous_id
    supervisor.shutdown()


def test_required_terminal_handler_runs_after_process_gate_is_released(supervisor):
    launch(supervisor)
    calls = []

    def handler(context):
        if context.event is Phase.STOPPED:
            entered = Event()
            thread = Thread(
                target=lambda: (
                    supervisor._gate.acquire(),
                    entered.set(),
                    supervisor._gate.release(),
                )
            )
            thread.start()
            try:
                assert entered.wait(2)
                assert supervisor.resources.log is None
                calls.append(context)
            finally:
                thread.join(2)

    supervisor.handle_event = handler
    supervisor.shutdown()
    assert len(calls) == 1


def test_background_monitor_detects_exit_without_status_requests(supervisor):
    supervisor.watch_exits = True
    supervisor.watch_interval = 0.01
    seen = Event()

    def observer(context):
        supervisor.fixture_events.append(context)
        if context.event is Phase.FAILED:
            seen.set()

    supervisor.publish = observer
    launch(supervisor)
    supervisor.fixture_child.poll = lambda: 9
    assert seen.wait(2)
    assert supervisor.fixture_events[-1].exit_code == 9
    assert supervisor.resources.log is None


def test_launch_rejection_has_one_terminal_failure_without_stopping_a_child(supervisor):
    assert supervisor.launch(lambda: LaunchRejected("missing entry")) == "missing entry"
    supervisor.shutdown()
    assert [event.event for event in supervisor.fixture_events] == [
        Phase.STARTING,
        Phase.FAILED,
    ]
    assert supervisor.fixture_events[-1].reason == "missing entry"
    supervisor.fixture_popen.assert_not_called()


@pytest.mark.parametrize("stage", ["prepare", "spawn", "wait"])
def test_launch_exception_releases_log_and_reports_original_error(supervisor, stage):
    error = OSError(f"{stage} failed")
    prepare = MagicMock(return_value=supervisor.fixture_plan)
    handle = None
    if stage == "prepare":
        prepare.side_effect = error
    elif stage == "spawn":

        def fail_spawn(_command, **kwargs):
            nonlocal handle
            handle = kwargs["stdout"]
            raise error

        supervisor.fixture_popen.side_effect = fail_spawn
    else:
        supervisor.fixture_child.wait = MagicMock(side_effect=error)
        supervisor.stop_child = lambda process, **_kwargs: setattr(
            process, "running", False
        )
    with pytest.raises(OSError) as caught:
        supervisor.launch(prepare)
    assert caught.value is error
    assert supervisor.resources.log is None
    assert supervisor.resources.process is None
    assert [event.event for event in supervisor.fixture_events] == [
        Phase.STARTING,
        Phase.FAILED,
    ]
    assert supervisor.fixture_events[-1].error is error
    if handle is not None:
        assert handle.closed


def test_failed_launch_cleanup_preserves_original_error_if_termination_also_fails(
    supervisor,
):
    original = RuntimeError("wait failed")
    supervisor.fixture_child.wait = MagicMock(side_effect=original)
    supervisor.stop_child = MagicMock(side_effect=OSError("stop failed"))
    with pytest.raises(RuntimeError) as caught:
        launch(supervisor)
    assert caught.value is original
    assert supervisor.resources.process is supervisor.fixture_child
    assert supervisor.resources.log is None
    assert supervisor.fixture_events[-1].error is original


def test_early_child_exit_does_not_emit_started_or_duplicate_terminal_notification(
    supervisor,
):
    supervisor.fixture_child.outcomes = [4]
    assert launch(supervisor) == "exit 4"
    supervisor.shutdown()
    assert [event.event for event in supervisor.fixture_events] == [
        Phase.STARTING,
        Phase.FAILED,
    ]
    assert supervisor.fixture_events[-1].exit_code == 4
    assert supervisor.resources.process is None


def test_observer_exceptions_do_not_prevent_launch_or_shutdown(supervisor):
    def broken(context):
        supervisor.fixture_events.append(context)
        raise RuntimeError("observer failed")

    supervisor.publish = broken
    launch(supervisor)
    handle = supervisor.resources.log
    supervisor.shutdown()
    assert [event.event for event in supervisor.fixture_events] == [
        Phase.STARTING,
        Phase.STARTED,
        Phase.STOPPING,
        Phase.STOPPED,
    ]
    assert handle.closed
    assert not supervisor.running()


def test_reentrant_observer_cannot_recursively_start_or_stop_transition(supervisor):
    nested = []

    def observe(context):
        supervisor.fixture_events.append(context)
        nested.append(launch(supervisor))
        supervisor.shutdown()

    supervisor.publish = observe
    launch(supervisor)
    assert supervisor.running()
    supervisor.shutdown()
    assert len(nested) == 4
    assert all("正在启动或关闭" in result for result in nested)
    supervisor.fixture_popen.assert_called_once()


def test_concurrent_starts_prepare_and_spawn_exactly_once(supervisor):
    entered, proceed, second_started = Event(), Event(), Event()
    results, errors = [], []

    def prepare():
        entered.set()
        assert proceed.wait(timeout=5)
        return supervisor.fixture_plan

    def first():
        try:
            results.append(supervisor.launch(prepare))
        except BaseException as error:
            errors.append(error)

    def second():
        second_started.set()
        try:
            results.append(launch(supervisor))
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=first), Thread(target=second)]
    threads[0].start()
    try:
        assert entered.wait(timeout=5)
        threads[1].start()
        assert second_started.wait(timeout=5)
    finally:
        proceed.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=5)
    assert not errors
    assert not any(thread.is_alive() for thread in threads)
    assert any("已经在运行" in result for result in results)
    supervisor.fixture_popen.assert_called_once()


def test_shutdown_preserves_replacement_child_and_its_log(supervisor):
    launch(supervisor)
    original_handle = supervisor.resources.log
    replacement = FakeChild()
    replacement_handle = io.StringIO()

    def replace(process, **_kwargs):
        process.running = False
        supervisor.resources.process = replacement
        supervisor.resources.log = replacement_handle

    supervisor.stop_child = replace
    supervisor.shutdown()
    assert supervisor.resources.process is replacement
    assert supervisor.resources.log is replacement_handle
    assert original_handle.closed
    assert not replacement_handle.closed


@pytest.mark.parametrize("fails", [False, True])
def test_shutdown_failure_is_distinct_from_confirmed_exit(supervisor, fails):
    launch(supervisor)
    handle = supervisor.resources.log
    error = OSError("stop failed")
    supervisor.stop_child = MagicMock(side_effect=error if fails else None)
    if fails:
        with pytest.raises(OSError) as caught:
            supervisor.shutdown()
        assert caught.value is error
    else:
        supervisor.shutdown()
    assert handle.closed
    assert supervisor.fixture_events[-1].event is Phase.FAILED
    assert supervisor.fixture_events[-1].reason == "shutdown"
    assert supervisor.fixture_events[-1].exit_code is None


def test_facade_publishes_sdk_hooks_for_requestless_shutdown(tmp_path, monkeypatch):
    state = make_state(tmp_path, monkeypatch)
    dispatcher = PluginHookDispatcher()
    observed = []
    for phase in Phase:
        dispatcher.register_chat_process(phase, observed.append)
    monkeypatch.setattr(
        "plugin_system.host.service.get_plugin_hook_dispatcher", lambda: dispatcher
    )
    monkeypatch.setattr(
        chat.subprocess, "Popen", lambda *_args, **_kwargs: FakeChild(["timeout", 0])
    )
    chat._launch_chat(state, **launch_arguments())
    chat.shutdown_active_chat_process(wait_before_signal=0.5)
    assert [event.event for event in observed] == [
        Phase.STARTING,
        Phase.STARTED,
        Phase.STOPPING,
        Phase.STOPPED,
    ]
    assert all(event.session_id == "session-1" for event in observed)


def test_supervisor_default_resources_and_no_observers_are_usable(supervisor):
    supervisor.resources = MemoryProcessResources()
    supervisor.publish = lambda _context: None
    launch(supervisor)
    supervisor.shutdown()
    supervisor.shutdown()
    assert not supervisor.running()

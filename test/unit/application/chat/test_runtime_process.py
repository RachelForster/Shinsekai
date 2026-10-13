"""Characterize the existing child-process lifecycle before extracting services."""

from __future__ import annotations

import io
import json
from pathlib import Path
import signal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.chat import runtime_process as chat
from application.chat.launch_args import CHAT_LAUNCH_CONFIG_ENV
from test.unit.application.chat.runtime_process_fakes import (
    FakeChild,
    launch_arguments,
    make_state,
)


@pytest.fixture
def state(tmp_path, monkeypatch):
    value = make_state(tmp_path, monkeypatch)
    yield value
    chat._close_chat_log_if_needed()


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_child_launch_is_hidden_or_in_its_own_process_group(monkeypatch, platform):
    monkeypatch.setattr(chat, "os", SimpleNamespace(name=platform))
    kwargs = chat._hidden_subprocess_kwargs()
    if platform == "nt":
        assert kwargs["creationflags"] & 0x08000000
        assert kwargs["creationflags"] & 0x00000200
    else:
        assert kwargs == {"start_new_session": True}


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_stop_escalates_signals_with_bounded_waits(monkeypatch, platform):
    monkeypatch.setattr(chat.signal, "SIGKILL", 9, raising=False)
    child = FakeChild(["timeout", "timeout", 0])
    groups = MagicMock()
    monkeypatch.setattr(chat, "os", SimpleNamespace(name=platform, killpg=groups))
    chat._stop_chat_process(child, wait_timeout=2.0)
    assert child.poll() == 0
    assert len(child.timeouts) == 3
    assert all(0.05 <= timeout <= 1.3 for timeout in child.timeouts)
    if platform == "nt":
        assert child.actions == [signal.SIGINT, "terminate", "kill"]
    else:
        assert [call.args for call in groups.call_args_list] == [
            (child.pid, signal.SIGINT),
            (child.pid, signal.SIGTERM),
            (child.pid, signal.SIGKILL),
        ]


def test_stop_does_not_signal_an_exited_child():
    child = FakeChild()
    child.running = False
    chat._stop_chat_process(child, wait_timeout=0)
    assert child.actions == []
    assert child.timeouts == []


@pytest.mark.parametrize("error", [OSError("closed"), ValueError("invalid handle")])
def test_signal_ignores_lost_handles(monkeypatch, error):
    child = FakeChild()
    child.send_signal = MagicMock(side_effect=error)
    monkeypatch.setattr(chat, "os", SimpleNamespace(name="nt"))
    chat._signal_process_tree(child, signal.SIGINT)
    child.send_signal.assert_called_once_with(signal.SIGINT)


@pytest.mark.parametrize("group_error", [ProcessLookupError(), OSError("no group")])
def test_signal_falls_back_to_child_when_group_is_unavailable(monkeypatch, group_error):
    child = FakeChild()
    monkeypatch.setattr(
        chat,
        "os",
        SimpleNamespace(name="posix", killpg=MagicMock(side_effect=group_error)),
    )
    chat._signal_process_tree(child, signal.SIGTERM)
    assert child.actions == [signal.SIGTERM]


def test_signal_does_not_fall_back_when_missing_group_has_already_exited(monkeypatch):
    child = FakeChild()
    child.running = False
    monkeypatch.setattr(
        chat,
        "os",
        SimpleNamespace(
            name="posix", killpg=MagicMock(side_effect=ProcessLookupError())
        ),
    )
    chat._signal_process_tree(child, signal.SIGTERM)
    assert child.actions == []


@pytest.mark.parametrize("outcome,expected", [(0, True), ("timeout", False)])
def test_wait_normalizes_negative_timeout(outcome, expected):
    child = FakeChild([outcome])
    assert chat._wait_process_exit(child, -1) is expected
    assert child.timeouts == [0]


def test_shutdown_waits_for_requested_graceful_exit_before_signalling(
    state, monkeypatch
):
    child = FakeChild([0])
    log = io.StringIO()
    monkeypatch.setattr(chat, "_main_chat_process", child)
    monkeypatch.setattr(chat, "_main_chat_log_file", log)
    chat.shutdown_active_chat_process(wait_timeout=2, wait_before_signal=0.8)
    assert child.actions == []
    assert child.timeouts == [0.8]
    assert chat._main_chat_process is None
    assert log.closed


def test_shutdown_cleans_up_even_when_stop_raises(state, monkeypatch):
    child = FakeChild()
    log = io.StringIO()
    monkeypatch.setattr(chat, "_main_chat_process", child)
    monkeypatch.setattr(chat, "_main_chat_log_file", log)
    monkeypatch.setattr(
        chat, "_stop_chat_process", MagicMock(side_effect=RuntimeError("stop failed"))
    )
    with pytest.raises(RuntimeError, match="stop failed"):
        chat.shutdown_active_chat_process()
    assert chat._main_chat_process is None
    assert log.closed


def test_shutdown_does_not_forget_a_replacement_process(state, monkeypatch):
    original, replacement = FakeChild(), FakeChild()
    monkeypatch.setattr(chat, "_main_chat_process", original)
    monkeypatch.setattr(
        chat,
        "_stop_chat_process",
        lambda *_args, **_kwargs: setattr(chat, "_main_chat_process", replacement),
    )
    chat.shutdown_active_chat_process()
    assert chat._main_chat_process is replacement


def test_shutdown_reaps_an_already_exited_child(state, monkeypatch):
    child = FakeChild()
    child.running = False
    log = io.StringIO()
    monkeypatch.setattr(chat, "_main_chat_process", child)
    monkeypatch.setattr(chat, "_main_chat_log_file", log)
    chat.shutdown_active_chat_process()
    assert chat._main_chat_process is None
    assert log.closed


def test_runtime_closing_takes_precedence_over_process_status(state, monkeypatch):
    monkeypatch.setattr(chat, "_main_chat_process", FakeChild())
    assert chat._chat_runtime_status(state)["state"] == "running"
    chat._set_chat_runtime_closing(state, True)
    assert chat._chat_runtime_status(state) == {
        "state": "closing",
        "chatProcessRunning": True,
        "chatRuntimeClosing": True,
    }
    del state.chat_runtime_lock
    chat._set_chat_runtime_closing(state, False)
    assert not chat._chat_runtime_closing(state)


def test_log_closing_is_idempotent_even_if_handle_close_fails(state, monkeypatch):
    handle = MagicMock()
    handle.close.side_effect = OSError("closed elsewhere")
    monkeypatch.setattr(chat, "_main_chat_log_file", handle)
    chat._close_chat_log_if_needed()
    chat._close_chat_log_if_needed()
    assert chat._main_chat_log_file is None
    handle.close.assert_called_once_with()


def test_popen_uses_log_stream_and_unbuffered_environment(state, monkeypatch, tmp_path):
    child = FakeChild()
    popen = MagicMock(return_value=child)
    monkeypatch.setattr(chat.subprocess, "Popen", popen)
    original_env = {"fixture": "value"}
    process, log_path = chat._popen_chat_process(
        ["python", "main.py"], cwd=tmp_path, env=original_env
    )
    assert process is child
    kwargs = popen.call_args.kwargs
    assert kwargs["env"] == {"fixture": "value", "PYTHONUNBUFFERED": "1"}
    assert original_env == {"fixture": "value"}
    assert kwargs["stdout"] is chat._main_chat_log_file
    assert kwargs["stderr"] == chat.subprocess.STDOUT
    assert "main.py launch" in log_path.read_text(encoding="utf-8")


def test_log_tail_and_missing_dependency_diagnostics(state, tmp_path):
    log = tmp_path / "failure.log"
    log.write_text(
        "prefix\nModuleNotFoundError: No module named 'opencc'", encoding="utf-8"
    )
    assert chat._tail_text(log, 6) == "pencc'"
    message = chat._failed_launch_message(1, log)
    assert "opencc-python-reimplemented" in message
    assert str(log) in message
    assert chat._tail_text(tmp_path / "missing.log") == ""


def test_launch_refuses_duplicate_process_before_mutating_config(state, monkeypatch):
    monkeypatch.setattr(chat, "_main_chat_process", FakeChild())
    assert "12345" in chat._launch_chat(state, **launch_arguments())
    state.config_manager.save_system_config.assert_not_called()


def test_source_launch_preserves_environment_configuration_and_template(
    state, monkeypatch, tmp_path
):
    child = FakeChild()
    popen = MagicMock(return_value=child)
    monkeypatch.setattr(chat.subprocess, "Popen", popen)
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    state.chat_stream.http_base = "http://127.0.0.1:8787/"
    state.chat_session.update(
        playerCharacter="Player", readPlayerSpeech=True, allowPlayerDialogue=False
    )
    state.config_manager.config.api_config.tts_provider = ""
    message = chat._launch_chat(
        state,
        **launch_arguments(
            character_names=["Alice"],
            use_cg=True,
            workflow_path="workflow.yaml",
            stream_endpoint="ws://fixture/chat",
            init_stream_endpoint="ws://fixture/init",
            media_selection_mode="semantic",
            show_initial_sprite=False,
        ),
    )
    assert "12345" in message
    args, kwargs = popen.call_args
    assert args[0] == [chat.sys.executable, str(tmp_path / "main.py")]
    env = kwargs["env"]
    payload = json.loads(env[CHAT_LAUNCH_CONFIG_ENV])
    assert payload["characters"] == '["Alice"]'
    assert payload["tts"] == "gpt-sovits"
    assert payload["t2i"] == "ComfyUI"
    assert payload["workflow"] == "workflow.yaml"
    assert payload["stream_endpoint"] == "ws://fixture/chat"
    assert payload["init_stream_endpoint"] == "ws://fixture/init"
    assert payload["media_selection_mode"] == "semantic"
    assert payload["show_initial_sprite"] is False
    assert payload["use_current_template_for_history"] is True
    assert env["SHINSEKAI_MEMORY_SERVICE_URL"] == "http://127.0.0.1:8787/api/memory"
    assert env["SHINSEKAI_MEMORY_SERVICE_TOKEN"] == "fixture-memory-token"
    assert Path(payload["history"]).is_dir()
    state.config_manager.save_system_config.assert_called_once_with()
    meta = json.loads(
        (Path(state.template_dir_path) / chat.TEMP_SPLIT_META).read_text(
            encoding="utf-8"
        )
    )
    assert meta == {"scenario": "scenario", "system": "system"}


@pytest.mark.parametrize("frozen", [False, True])
def test_missing_entrypoint_is_reported_without_spawning(
    state, monkeypatch, tmp_path, frozen
):
    monkeypatch.setattr(chat.sys, "frozen", frozen, raising=False)
    (tmp_path / "main.py").unlink()
    popen = MagicMock()
    monkeypatch.setattr(chat.subprocess, "Popen", popen)
    message = chat._launch_chat(state, **launch_arguments())
    assert "main.exe" in message if frozen else "main.py" in message
    assert "启动失败" in message
    popen.assert_not_called()


def test_frozen_launch_prefers_nested_executable(state, monkeypatch, tmp_path):
    nested = tmp_path / "main" / "main.exe"
    nested.parent.mkdir()
    nested.touch()
    (tmp_path / "main.exe").touch()
    monkeypatch.setattr(chat.sys, "frozen", True, raising=False)
    popen = MagicMock(return_value=FakeChild())
    monkeypatch.setattr(chat.subprocess, "Popen", popen)
    assert "已启动" in chat._launch_chat(state, **launch_arguments())
    assert popen.call_args.args[0] == [str(nested)]


def test_early_child_exit_is_reported_and_log_is_closed(state, monkeypatch):
    monkeypatch.setattr(
        chat.subprocess, "Popen", MagicMock(return_value=FakeChild([3]))
    )
    assert "退出码 3" in chat._launch_chat(state, **launch_arguments())
    assert chat._main_chat_log_file is None


def test_spawn_error_propagates(state, monkeypatch):
    monkeypatch.setattr(
        chat.subprocess, "Popen", MagicMock(side_effect=OSError("spawn failed"))
    )
    with pytest.raises(OSError, match="spawn failed"):
        chat._launch_chat(state, **launch_arguments())


def test_path_candidates_are_unique_and_keep_explicit_application_root(
    state, tmp_path, monkeypatch
):
    del state.app_root_dir
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", str(tmp_path))
    assert chat._app_root(state) == tmp_path
    assert chat._main_exe_candidates(state) == [
        tmp_path / "main" / "main.exe",
        tmp_path / "main.exe",
    ]
    assert chat._unique_paths([tmp_path, tmp_path / "."]) == [tmp_path]
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", str(tmp_path / "absent"))
    monkeypatch.setattr(chat, "runtime_app_root", lambda: tmp_path)
    assert chat._app_root(state) == tmp_path
    monkeypatch.setattr(chat.sys, "frozen", True, raising=False)
    monkeypatch.setattr(chat.sys, "executable", str(tmp_path / "main" / "main.exe"))
    assert chat._release_root() == tmp_path

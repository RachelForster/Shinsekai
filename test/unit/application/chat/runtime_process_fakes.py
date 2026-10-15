"""Small transport/process doubles shared by chat-runtime characterization tests."""

from __future__ import annotations

from core.chat_history.storage import chat_history_active_path

import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from application.chat import runtime_process as chat
from config.schema import ApiConfig, SystemConfig


class FakeChild:
    pid = 12345

    def __init__(self, outcomes=None):
        self.running = True
        self.outcomes = list(outcomes or ["timeout"])
        self.actions = []
        self.timeouts = []

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0) if self.outcomes else "timeout"
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("fixture", timeout)
        self.running = False
        return outcome

    def send_signal(self, signum):
        self.actions.append(signum)

    def terminate(self):
        self.actions.append("terminate")

    def kill(self):
        self.actions.append("kill")


class RecordingStream:
    def __init__(self):
        self.snapshot = {
            "sessionId": "session-1",
            "status": "idle",
            "historyEntries": [],
            "userDisplayName": "Player",
            "dialogText": "previous",
        }
        self.commands = []
        self.updates = []
        self.events = []
        self.reads = []
        self.accept = True

    def get_snapshot(self, session_id, *, renderer_id=""):
        self.reads.append((session_id, renderer_id))
        return dict(self.snapshot) if self.snapshot is not None else None

    def send_command(self, session_id, command):
        self.commands.append((session_id, dict(command)))
        return self.accept

    def update_session_snapshot(self, session_id, patch):
        self.updates.append((session_id, dict(patch)))
        self.snapshot.update(patch)

    def publish_event(self, session_id, event):
        self.events.append((session_id, dict(event)))
        return self.accept


def make_state(tmp_path, monkeypatch):
    manager = SimpleNamespace(
        config=SimpleNamespace(
            api_config=ApiConfig(), system_config=SystemConfig(), characters=[]
        ),
        save_system_config=MagicMock(),
        save_api_config=MagicMock(),
        get_character_by_name=MagicMock(return_value=None),
        get_background_by_name=MagicMock(return_value=None),
    )
    templates = tmp_path / "data" / "character_templates"
    templates.mkdir(parents=True)
    (tmp_path / "main.py").write_text(
        "# never executed by these tests\n", encoding="utf-8"
    )
    state = SimpleNamespace(
        config_manager=manager,
        chat_session={
            "sessionId": "session-1",
            "historyPath": str(tmp_path / "history"),
        },
        chat_stream=RecordingStream(),
        project_root_dir=str(tmp_path),
        app_root_dir=str(tmp_path),
        template_dir_path=str(templates),
        template_generator=None,
        history_dir=str(tmp_path / "history"),
        chat_runtime_lock=threading.Lock(),
        chat_runtime_closing=False,
        story_session=None,
        mobile_access_service=None,
        auth_token="fixture-memory-token",
    )
    monkeypatch.setattr(chat._supervisor.resources, "process", None)
    monkeypatch.setattr(chat._supervisor.resources, "log", None)
    monkeypatch.setattr(chat, "runtime_project_root", lambda: tmp_path)
    monkeypatch.setattr(chat._launch_preparation, "project_root", lambda: tmp_path)
    monkeypatch.setattr(chat, "runtime_source_root", lambda: tmp_path)
    # Even on POSIX no characterization test may signal an actual process group.
    monkeypatch.setattr(chat.os, "killpg", MagicMock(), raising=False)
    return state


def launch_arguments(**overrides):
    values = dict(
        history_file="",
        init_sprite_path="",
        room_id="42",
        selected_bg="",
        system_template="system",
        use_cg=False,
        user_scenario="scenario",
    )
    values.update(overrides)
    return values


def write_messages(state, messages):
    path = chat_history_active_path(Path(state.chat_session["historyPath"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    return path

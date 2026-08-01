import json
import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from application.chat import runtime_process as chat
from application.runtime.dependencies import runtime_dependency_error_from_text
from core.sprite.sprite_cli import CHAT_LAUNCH_CONFIG_ENV


class _SystemConfig:
    chat_ui_runtime_mode = "react"
    live_room_id = ""

    def model_copy(self, *, deep: bool):
        clone = _SystemConfig()
        clone.chat_ui_runtime_mode = self.chat_ui_runtime_mode
        clone.live_room_id = self.live_room_id
        return clone


class _ApiConfig:
    tts_provider = "none"


class _AppConfig:
    system_config = _SystemConfig()
    api_config = _ApiConfig()


class _ConfigManager:
    def __init__(self):
        self.config = _AppConfig()

    def save_system_config(self):
        pass


def test_chat_app_root_rejects_whitespace_instead_of_falling_back(
    tmp_path,
    monkeypatch,
):
    fallback = tmp_path / "fallback-app"
    fallback.mkdir()
    monkeypatch.setenv("SHINSEKAI_APP_ROOT", fallback.as_posix())

    with pytest.raises(ValueError, match="app root"):
        chat._app_root(SimpleNamespace(app_root_dir="   "))


class _DummyProcess:
    pid = 12345

    def poll(self):
        return None

    def wait(self, timeout=None):
        raise chat.subprocess.TimeoutExpired("main.py", timeout)


class _DummyClosableProcess:
    pid = 67890

    def __init__(self):
        self.running = True
        self.signals = []

    def poll(self):
        return None if self.running else 0

    def send_signal(self, sig):
        self.signals.append(sig)
        self.running = False

    def terminate(self):
        self.running = False

    def kill(self):
        self.running = False

    def wait(self, timeout=None):
        self.running = False
        return 0


class _ChatStreamForClose:
    def __init__(self, process=None):
        self.closed = []
        self.commands = []
        self.deleted = []
        self.process = process
        self.snapshot = {
            "dialogText": "",
            "eventSeq": 3,
            "historyEntries": [],
            "inputDraft": "",
            "options": [],
            "sessionId": "session-1",
            "sprites": [],
            "status": "idle",
            "wsUrl": "ws://127.0.0.1:8788/ws",
        }

    def get_snapshot(self, session_id: str):
        if session_id != "session-1":
            return None
        return dict(self.snapshot)

    def close_session(self, session_id: str, *, reason: str = "聊天会话已结束。"):
        self.closed.append((session_id, reason))
        self.snapshot["notificationText"] = reason
        self.snapshot["sessionClosedReason"] = reason
        self.snapshot["status"] = "idle"

    def send_command(self, session_id: str, command: dict):
        self.commands.append((session_id, command))
        if self.process is not None and command.get("type") == "close-session":
            self.process.running = False
        return True

    def delete_session(self, session_id: str):
        self.deleted.append(session_id)


def test_chat_log_path_rejects_symlinked_log_storage(tmp_path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    try:
        (project / "logs").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        chat._chat_log_path(project)

    assert list(external.iterdir()) == []


def test_chat_log_path_rejects_symlinked_log_file(tmp_path):
    project = tmp_path / "project"
    log_dir = project / "logs"
    log_dir.mkdir(parents=True)
    target = log_dir / "other.log"
    target.write_text("keep", encoding="utf-8")
    try:
        (log_dir / "main.log").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        chat._chat_log_path(project)

    assert target.read_text(encoding="utf-8") == "keep"


def test_chat_launch_file_rejects_linked_leaf_and_parent(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "main.py"
    target.write_text("print('safe')", encoding="utf-8")
    linked_file = tmp_path / "linked-main.py"
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_file.symlink_to(target)
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    assert chat._launch_file(target) == target
    assert chat._launch_file(linked_file) is None
    assert chat._launch_file(linked_parent / "main.py") is None


def test_chat_launch_candidate_deduplication_does_not_hide_link_target(
    tmp_path,
):
    target = tmp_path / "main.exe"
    alias = tmp_path / "linked-main.exe"
    target.write_bytes(b"safe")
    try:
        alias.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    assert chat._unique_paths([alias, target]) == [alias, target]


def test_chat_process_is_stopped_when_entry_changes_during_spawn(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    entry = tmp_path / "main.py"
    project.mkdir()
    entry.write_text("print('approved')", encoding="utf-8")
    entry_snapshot = chat._launch_file_snapshot(entry)
    assert entry_snapshot is not None
    process = _DummyClosableProcess()

    def replace_during_spawn(*_args, **_kwargs):
        entry.write_text(
            "print('replacement-is-longer')",
            encoding="utf-8",
        )
        return process

    monkeypatch.setattr(
        chat.subprocess,
        "Popen",
        replace_during_spawn,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        chat._popen_chat_process(
            [str(entry)],
            cwd=project,
            env={},
            required_files=(entry_snapshot,),
        )

    assert process.running is False
    assert chat._main_chat_log_file is None


def test_chat_process_is_stopped_when_application_root_changes_during_spawn(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    application = tmp_path / "application"
    preserved = tmp_path / "application-preserved"
    project.mkdir()
    application.mkdir()
    application, application_identity = chat.capture_directory_identity(
        application,
        field="chat application root",
    )
    process = _DummyClosableProcess()

    def replace_during_spawn(*_args, **_kwargs):
        application.rename(preserved)
        application.mkdir()
        return process

    monkeypatch.setattr(chat.subprocess, "Popen", replace_during_spawn)

    with pytest.raises(PermissionError, match="identity changed"):
        chat._popen_chat_process(
            ["chat"],
            cwd=project,
            env={},
            required_directories=((application, application_identity),),
        )

    assert process.running is False
    assert chat._main_chat_log_file is None


def test_chat_process_is_stopped_when_history_session_changes_during_spawn(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    session = project / "data" / "chat_history" / "session"
    preserved = project / "data" / "chat_history" / "session-preserved"
    session.mkdir(parents=True)
    required_files, required_directories = chat._history_launch_snapshots(
        session
    )
    process = _DummyClosableProcess()

    def replace_during_spawn(*_args, **_kwargs):
        session.rename(preserved)
        session.mkdir()
        return process

    monkeypatch.setattr(chat.subprocess, "Popen", replace_during_spawn)

    with pytest.raises(PermissionError, match="identity changed"):
        chat._popen_chat_process(
            ["chat"],
            cwd=project,
            env={},
            required_files=required_files,
            required_directories=required_directories,
        )

    assert process.running is False
    assert chat._main_chat_log_file is None


def test_launch_chat_uses_source_main_py_with_project_root_cwd(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)

    captured = {}

    def fake_popen(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _DummyProcess()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.delenv("SHINSEKAI_CHAT_ATTACHMENTS_ROOT", raising=False)
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chat.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(chat, "_main_chat_process", None)

    state = SimpleNamespace(
        app_root_dir=str(app_root),
        config_manager=_ConfigManager(),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
    )

    message = chat._launch_chat(
        state,
        history_file="",
        init_sprite_path="",
        room_id="",
        selected_bg="",
        system_template="system",
        use_cg=False,
        user_scenario="scenario",
    )

    assert message == "聊天进程已启动！PID: 12345"
    assert captured["cmd"][1] == str(chat._source_root() / "main.py")
    assert captured["cwd"] == str(project_root)
    assert captured["env"]["SHINSEKAI_PROJECT_ROOT"] == str(project_root)
    assert captured["env"]["EASYAI_PROJECT_ROOT"] == str(project_root)
    assert captured["env"]["SHINSEKAI_APP_ROOT"] == str(app_root)
    assert captured["env"]["SHINSEKAI_CHAT_ATTACHMENTS_ROOT"] == str(
        project_root / "data" / "chat_attachments"
    )
    assert not (app_root / "data").exists()
    assert captured["env"]["SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG"] == "1"
    assert captured["cmd"][1] != str(project_root / "main.py")
    assert json.loads(captured["env"][CHAT_LAUNCH_CONFIG_ENV])["template"] == "_temp"


def test_launch_chat_imports_external_json_before_starting_child(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    external_history = tmp_path / "external" / "session.json"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    external_history.parent.mkdir()
    external_payload = '[{"role":"user","content":"import me"}]'
    external_history.write_text(external_payload, encoding="utf-8")
    captured = {}

    def fake_popen(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return _DummyProcess()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chat.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(chat, "_main_chat_process", None)

    state = SimpleNamespace(
        app_root_dir=str(app_root),
        config_manager=_ConfigManager(),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
    )

    message = chat._launch_chat(
        state,
        history_file=str(external_history),
        init_sprite_path="",
        room_id="",
        selected_bg="",
        system_template="system",
        use_cg=False,
        user_scenario="scenario",
    )

    assert message == "聊天进程已启动！PID: 12345"
    launch_config = json.loads(captured["env"][CHAT_LAUNCH_CONFIG_ENV])
    managed_history = Path(launch_config["history"])
    assert managed_history.is_dir()
    assert managed_history.is_relative_to(history_dir)
    assert (managed_history / "active.json").read_text(encoding="utf-8") == external_payload
    assert external_history.read_text(encoding="utf-8") == external_payload
    assert f"--history={managed_history}" in captured["cmd"]


def test_launch_chat_stops_child_when_runtime_template_changes_during_spawn(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    process = _DummyClosableProcess()

    def replace_during_spawn(*_args, **_kwargs):
        (template_dir / "_temp.txt").write_text(
            "replacement-is-longer",
            encoding="utf-8",
        )
        return process

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chat.subprocess, "Popen", replace_during_spawn)
    monkeypatch.setattr(chat, "_main_chat_process", None)

    state = SimpleNamespace(
        app_root_dir=str(app_root),
        config_manager=_ConfigManager(),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
    )

    with pytest.raises(PermissionError, match="identity changed"):
        chat._launch_chat(
            state,
            history_file="",
            init_sprite_path="",
            room_id="",
            selected_bg="",
            system_template="system",
            use_cg=False,
            user_scenario="scenario",
        )

    assert process.running is False
    assert chat._main_chat_log_file is None


def test_launch_chat_passes_stream_endpoint(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)

    captured = {}

    def fake_popen(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _DummyProcess()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chat.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(chat, "_main_chat_process", None)

    state = SimpleNamespace(
        app_root_dir=str(app_root),
        config_manager=_ConfigManager(),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
    )

    message = chat._launch_chat(
        state,
        history_file="",
        init_sprite_path="",
        room_id="",
        selected_bg="",
        system_template="system",
        use_cg=False,
        user_scenario="scenario",
        stream_endpoint="ws://127.0.0.1:8788/ws?sessionId=test&role=producer",
        init_stream_endpoint="ws://127.0.0.1:8788/ws?sessionId=init&role=producer",
    )

    assert message == "聊天进程已启动！PID: 12345"
    assert "--stream-endpoint=ws://127.0.0.1:8788/ws?sessionId=test&role=producer" in captured["cmd"]
    assert "--init-stream-endpoint=ws://127.0.0.1:8788/ws?sessionId=init&role=producer" in captured["cmd"]
    launch_config = json.loads(captured["env"][CHAT_LAUNCH_CONFIG_ENV])
    assert launch_config["stream_endpoint"] == (
        "ws://127.0.0.1:8788/ws?sessionId=test&role=producer"
    )
    assert launch_config["init_stream_endpoint"] == (
        "ws://127.0.0.1:8788/ws?sessionId=init&role=producer"
    )


def test_launch_chat_passes_memory_service_env(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)

    captured = {}

    def fake_popen(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _DummyProcess()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chat.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(chat, "_main_chat_process", None)

    state = SimpleNamespace(
        app_root_dir=str(app_root),
        auth_token="bridge-secret",
        chat_stream=SimpleNamespace(http_base="http://127.0.0.1:8787"),
        config_manager=_ConfigManager(),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
    )

    message = chat._launch_chat(
        state,
        history_file="",
        init_sprite_path="",
        room_id="",
        selected_bg="",
        system_template="system",
        use_cg=False,
        user_scenario="scenario",
    )

    assert "12345" in message
    assert captured["env"]["SHINSEKAI_MEMORY_SERVICE_URL"] == "http://127.0.0.1:8787/api/memory"
    assert captured["env"]["SHINSEKAI_MEMORY_SERVICE_OWNER"] == "0"
    assert captured["env"]["SHINSEKAI_MEMORY_SERVICE_TOKEN"] == "bridge-secret"


def test_launch_chat_passes_workflow_path(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    workflow_path = project_root / "test" / "e2e" / "live_bridge_runtime.yaml"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text("nodes: []\nedges: []\n", encoding="utf-8")

    captured = {}

    def fake_popen(cmd, *, cwd, env, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _DummyProcess()

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", str(project_root))
    monkeypatch.setattr(chat.sys, "frozen", False, raising=False)
    monkeypatch.setattr(chat.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(chat, "_main_chat_process", None)

    state = SimpleNamespace(
        app_root_dir=str(app_root),
        config_manager=_ConfigManager(),
        history_dir=str(history_dir),
        template_dir_path=str(template_dir),
    )

    message = chat._launch_chat(
        state,
        history_file="",
        init_sprite_path="",
        room_id="",
        selected_bg="",
        system_template="system",
        use_cg=False,
        user_scenario="scenario",
        workflow_path=str(workflow_path),
    )

    assert message == "聊天进程已启动！PID: 12345"
    assert f"--workflow={workflow_path}" in captured["cmd"]
    assert json.loads(captured["env"][CHAT_LAUNCH_CONFIG_ENV])["workflow"] == str(
        workflow_path
    )


def test_launch_chat_rejects_inline_workflow_content_before_starting_process(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "project"
    app_root = tmp_path / "Shinsekai"
    template_dir = project_root / "data" / "character_templates"
    history_dir = project_root / "data" / "chat_history"
    app_root.mkdir()
    template_dir.mkdir(parents=True)
    history_dir.mkdir(parents=True)

    monkeypatch.setenv("EASYAI_PROJECT_ROOT", project_root.as_posix())
    monkeypatch.setattr(chat, "_main_chat_process", None)
    monkeypatch.setattr(chat.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not start"))

    state = SimpleNamespace(
        app_root_dir=app_root.as_posix(),
        config_manager=_ConfigManager(),
        history_dir=history_dir.as_posix(),
        template_dir_path=template_dir.as_posix(),
    )

    with pytest.raises(ValueError, match="control characters"):
        chat._launch_chat(
            state,
            history_file="",
            init_sprite_path="",
            room_id="",
            selected_bg="",
            system_template="system",
            use_cg=False,
            user_scenario="scenario",
            workflow_path="nodes: []\nedges: []\n",
        )


def test_runtime_dependency_error_maps_opencc_package():
    error = runtime_dependency_error_from_text("ModuleNotFoundError: No module named 'opencc'")

    assert error == {
        "kind": "missing_dependency",
        "message": "Missing Python module: opencc",
        "moduleName": "opencc",
        "packageName": "opencc-python-reimplemented",
    }


def test_close_chat_requests_graceful_runtime_shutdown_and_marks_session_closed(monkeypatch):
    process = _DummyClosableProcess()
    chat_stream = _ChatStreamForClose(process)
    mobile_access = MagicMock()
    mobile_access.snapshot.return_value = None
    monkeypatch.setattr(chat, "_main_chat_process", process)

    state = SimpleNamespace(
        chat_session={"sessionId": "session-1", "voiceLanguage": "ja"},
        chat_stream=chat_stream,
        config_manager=_ConfigManager(),
        mobile_access_service=mobile_access,
    )

    snapshot = chat._close_chat(state)

    assert process.signals == []
    assert chat_stream.commands[0][0] == "session-1"
    assert chat_stream.commands[0][1]["type"] == "close-session"
    assert isinstance(chat_stream.commands[0][1]["cmdId"], str)
    assert chat_stream.closed == [("session-1", "聊天会话已结束。")]
    assert chat_stream.deleted == ["session-1"]
    assert state.chat_session["sessionId"] == ""
    assert snapshot["sessionClosedReason"] == "聊天会话已结束。"
    assert snapshot["runtimeMode"] == "react"
    mobile_access.stop.assert_called_once_with()


def test_shutdown_active_chat_process_stops_child_without_request_state(monkeypatch):
    process = _DummyClosableProcess()
    monkeypatch.setattr(chat, "_main_chat_process", process)

    chat.shutdown_active_chat_process()

    assert process.signals == [signal.SIGINT]
    assert chat._main_chat_process is None

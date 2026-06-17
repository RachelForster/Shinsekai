import signal
from types import SimpleNamespace

from frontend_bridge_core import chat
from frontend_bridge_core.runtime_dependencies import runtime_dependency_error_from_text


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
    def __init__(self):
        self.closed = []
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
    assert captured["env"]["EASYAI_PROJECT_ROOT"] == str(project_root)
    assert captured["env"]["SHINSEKAI_APP_ROOT"] == str(app_root)
    assert captured["env"]["SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG"] == "1"
    assert captured["cmd"][1] != str(project_root / "main.py")


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
    )

    assert message == "聊天进程已启动！PID: 12345"
    assert "--stream-endpoint=ws://127.0.0.1:8788/ws?sessionId=test&role=producer" in captured["cmd"]


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


def test_runtime_dependency_error_maps_opencc_package():
    error = runtime_dependency_error_from_text("ModuleNotFoundError: No module named 'opencc'")

    assert error == {
        "kind": "missing_dependency",
        "message": "Missing Python module: opencc",
        "moduleName": "opencc",
        "packageName": "opencc-python-reimplemented",
    }


def test_close_chat_sends_sigint_and_marks_runtime_session_closed(monkeypatch):
    process = _DummyClosableProcess()
    chat_stream = _ChatStreamForClose()
    monkeypatch.setattr(chat, "_main_chat_process", process)

    state = SimpleNamespace(
        chat_session={"sessionId": "session-1", "voiceLanguage": "ja"},
        chat_stream=chat_stream,
        config_manager=_ConfigManager(),
    )

    snapshot = chat._close_chat(state)

    assert process.signals == [signal.SIGINT]
    assert chat_stream.closed == [("session-1", "聊天会话已结束。")]
    assert snapshot["sessionClosedReason"] == "聊天会话已结束。"
    assert snapshot["runtimeMode"] == "react"


def test_shutdown_active_chat_process_stops_child_without_request_state(monkeypatch):
    process = _DummyClosableProcess()
    monkeypatch.setattr(chat, "_main_chat_process", process)

    chat.shutdown_active_chat_process()

    assert process.signals == [signal.SIGINT]
    assert chat._main_chat_process is None

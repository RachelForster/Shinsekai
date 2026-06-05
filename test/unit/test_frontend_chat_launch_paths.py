from types import SimpleNamespace

from frontend_bridge_core import chat
from frontend_bridge_core.runtime_dependencies import runtime_dependency_error_from_text


class _SystemConfig:
    live_room_id = ""

    def model_copy(self, *, deep: bool):
        clone = _SystemConfig()
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
    assert captured["cmd"][1] != str(project_root / "main.py")


def test_runtime_dependency_error_maps_opencc_package():
    error = runtime_dependency_error_from_text("ModuleNotFoundError: No module named 'opencc'")

    assert error == {
        "message": "Missing Python module: opencc",
        "moduleName": "opencc",
        "packageName": "opencc-python-reimplemented",
    }

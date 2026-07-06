import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from frontend_bridge_core.chat import _chat_runtime_mode, _chat_snapshot
from frontend_bridge_core.handler import BRIDGE_AUTH_HEADER, CHAT_RUNTIME_READY_TIMEOUT_SECONDS, FrontendBridgeHandler


class _SystemConfig:
    live_room_id = ""
    voice_language = "ja"
    chat_ui_runtime_mode = "native"
    react_chat_fork_experimental_enabled = False
    react_chat_flowchart_experimental_enabled = False

    def model_copy(self, *, deep: bool):
        clone = _SystemConfig()
        clone.live_room_id = self.live_room_id
        clone.voice_language = self.voice_language
        clone.chat_ui_runtime_mode = self.chat_ui_runtime_mode
        clone.react_chat_fork_experimental_enabled = self.react_chat_fork_experimental_enabled
        clone.react_chat_flowchart_experimental_enabled = self.react_chat_flowchart_experimental_enabled
        return clone


class _Config:
    def __init__(self):
        self.system_config = _SystemConfig()
        self.characters = []
        self.background_list = [
            SimpleNamespace(name="默认房间", sprites=[{"path": "asset://default-bg.png"}])
        ]


class _ConfigManager:
    def __init__(self):
        self.config = _Config()

    def get_character_by_name(self, _name: str):
        return None

    def get_background_by_name(self, _name: str):
        for background in self.config.background_list:
            if background.name == _name:
                return background
        return None

    def save_system_config(self):
        pass


class _ChatStreamStub:
    def __init__(self):
        self.create_session_calls = []
        self.deleted_sessions = []
        self.snapshots = {}
        self.wait_calls = []
        self.wait_result = True

    def create_session(self, snapshot):
        self.create_session_calls.append(dict(snapshot))
        self.snapshots["session-1"] = {
            **dict(snapshot),
            "sessionId": "session-1",
            "wsUrl": "ws://127.0.0.1:8788/ws",
        }
        return {
            "producerEndpoint": "ws://127.0.0.1:8788/ws?sessionId=session-1&role=producer",
            "sessionId": "session-1",
            "wsUrl": "ws://127.0.0.1:8788/ws",
        }

    def delete_session(self, session_id: str):
        self.deleted_sessions.append(session_id)
        self.snapshots.pop(session_id, None)

    def get_snapshot(self, session_id: str):
        return dict(self.snapshots.get(session_id, {})) if session_id in self.snapshots else None

    def update_session_snapshot(self, session_id: str, snapshot: dict):
        current = dict(self.snapshots.get(session_id, {}))
        current.update(snapshot)
        current["sessionId"] = session_id
        current.setdefault("wsUrl", "ws://127.0.0.1:8788/ws")
        self.snapshots[session_id] = current

    def wait_for_producer(self, session_id: str, *, timeout: float = 5.0):
        self.wait_calls.append((session_id, timeout))
        return self.wait_result


class ChatRuntimeModeTests(unittest.TestCase):
    def test_chat_runtime_mode_defaults_to_native(self):
        state = SimpleNamespace(config_manager=_ConfigManager())

        self.assertEqual(_chat_runtime_mode(state), "native")

    def test_chat_snapshot_includes_runtime_mode(self):
        state = SimpleNamespace(
            chat_session={},
            chat_stream=None,
            config_manager=_ConfigManager(),
        )
        state.config_manager.config.system_config.chat_ui_runtime_mode = "native"

        snapshot = _chat_snapshot(state, "idle", "native started")

        self.assertEqual(snapshot["runtimeMode"], "native")
        self.assertEqual(snapshot["dialogText"], "native started")

    def test_chat_snapshot_keeps_transparent_background_empty(self):
        state = SimpleNamespace(
            chat_session={"backgroundName": "透明场景"},
            chat_stream=None,
            config_manager=_ConfigManager(),
        )

        snapshot = _chat_snapshot(state, "idle", "")

        self.assertEqual(snapshot["backgroundPath"], "")

    def test_chat_snapshot_does_not_fallback_empty_background_to_first_config_background(self):
        state = SimpleNamespace(
            chat_session={"backgroundName": ""},
            chat_stream=None,
            config_manager=_ConfigManager(),
        )

        snapshot = _chat_snapshot(state, "idle", "")

        self.assertEqual(snapshot["backgroundPath"], "")

    def test_chat_snapshot_uses_explicit_real_background(self):
        state = SimpleNamespace(
            chat_session={"backgroundName": "默认房间"},
            chat_stream=None,
            config_manager=_ConfigManager(),
        )

        snapshot = _chat_snapshot(state, "idle", "")

        self.assertEqual(snapshot["backgroundPath"], "asset://default-bg.png")

    def test_write_requests_require_local_origin_and_bridge_auth_token(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        handler.path = "/api/chat/command"
        handler.server = SimpleNamespace(state=SimpleNamespace(auth_token="secret"))
        handler.headers = {"Origin": "http://localhost:5173", BRIDGE_AUTH_HEADER: "secret"}

        handler._require_authorized_write("/api/chat/command")

        handler.headers = {"Origin": "http://localhost:5173", BRIDGE_AUTH_HEADER: "wrong"}
        with self.assertRaisesRegex(PermissionError, "invalid bridge auth token"):
            handler._require_authorized_write("/api/chat/command")

        handler.headers = {"Origin": "https://evil.example", BRIDGE_AUTH_HEADER: "secret"}
        with self.assertRaisesRegex(PermissionError, "request origin is not allowed"):
            handler._require_authorized_write("/api/chat/command")

    def test_launch_chat_skips_stream_session_in_native_mode(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "native"

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            history_dir.mkdir()
            template_dir = root / "templates"
            template_dir.mkdir()
            handler.server = SimpleNamespace(
                state=SimpleNamespace(
                    chat_session={},
                    chat_stream=chat_stream,
                    config_manager=config_manager,
                    history_dir=str(history_dir),
                    template_dir_path=str(template_dir),
                )
            )
            body = {
                "scenario": "scene",
                "system": "system",
                "templateId": "native-template",
                "templateName": "Native Template",
            }

            with patch("frontend_bridge_core.handler._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.handler._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ), patch(
                "frontend_bridge_core.handler._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ):
                snapshot = handler._launch_chat(body)

        self.assertEqual(chat_stream.create_session_calls, [])
        self.assertEqual(snapshot["runtimeMode"], "native")
        self.assertFalse(snapshot.get("sessionId"))

    def test_resume_last_chat_creates_stream_session_in_react_mode(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "react"

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            history_dir.mkdir()
            history_path = history_dir / "resume.json"
            history_path.write_text("[]", encoding="utf-8")
            template_dir = root / "templates"
            template_dir.mkdir()
            handler.server = SimpleNamespace(
                state=SimpleNamespace(
                    chat_session={},
                    chat_stream=chat_stream,
                    config_manager=config_manager,
                    history_dir=str(history_dir),
                    template_dir_path=str(template_dir),
                )
            )

            with patch(
                "frontend_bridge_core.handler._load_template_session_payload",
                return_value={
                    "background": "",
                    "historyPath": history_path.relative_to(Path.cwd()).as_posix(),
                    "roomId": "",
                    "scenario": "scene",
                    "selectedCharacters": [],
                    "system": "system",
                    "templateFileDropdown": "resume-template",
                    "voiceLanguage": "ja",
                },
            ), patch(
                "frontend_bridge_core.handler._resume_template_parts",
                return_value=("scene", "system", "resume-template"),
            ), patch(
                "frontend_bridge_core.handler._chat_process_running",
                return_value=False,
            ), patch(
                "frontend_bridge_core.handler._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ):
                snapshot = handler._resume_last_chat()

        self.assertEqual(len(chat_stream.create_session_calls), 1)
        self.assertEqual(chat_stream.wait_calls, [("session-1", CHAT_RUNTIME_READY_TIMEOUT_SECONDS)])
        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertEqual(snapshot["sessionId"], "session-1")

    def test_launch_chat_passes_workflow_path_to_runtime_process(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "react"

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            history_dir.mkdir()
            template_dir = root / "templates"
            template_dir.mkdir()
            handler.server = SimpleNamespace(
                state=SimpleNamespace(
                    chat_session={},
                    chat_stream=chat_stream,
                    config_manager=config_manager,
                    history_dir=str(history_dir),
                    template_dir_path=str(template_dir),
                )
            )
            body = {
                "scenario": "scene",
                "system": "system",
                "templateId": "react-template",
                "templateName": "React Template",
                "workflowPath": "test/e2e/live_bridge_runtime.yaml",
            }

            with patch("frontend_bridge_core.handler._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.handler._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ), patch(
                "frontend_bridge_core.handler._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat:
                snapshot = handler._launch_chat(body)

        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertEqual(snapshot["sessionId"], "session-1")
        self.assertEqual(chat_stream.wait_calls, [("session-1", CHAT_RUNTIME_READY_TIMEOUT_SECONDS)])
        self.assertEqual(launch_chat.call_args.kwargs["workflow_path"], "test/e2e/live_bridge_runtime.yaml")

    def test_launch_chat_raises_when_runtime_stream_never_becomes_ready(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        chat_stream.wait_result = False
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "react"

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            history_dir.mkdir()
            template_dir = root / "templates"
            template_dir.mkdir()
            handler.server = SimpleNamespace(
                state=SimpleNamespace(
                    chat_session={},
                    chat_stream=chat_stream,
                    config_manager=config_manager,
                    history_dir=str(history_dir),
                    template_dir_path=str(template_dir),
                )
            )
            body = {
                "scenario": "scene",
                "system": "system",
                "templateId": "react-timeout-template",
                "templateName": "React Timeout Template",
            }

            with patch("frontend_bridge_core.handler._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.handler._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ), patch(
                "frontend_bridge_core.handler._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ), patch(
                "frontend_bridge_core.handler._close_chat",
                return_value={"status": "idle"},
            ) as close_chat:
                with self.assertRaisesRegex(RuntimeError, "实时聊天会话未就绪"):
                    handler._launch_chat(body)

        self.assertEqual(chat_stream.wait_calls, [("session-1", CHAT_RUNTIME_READY_TIMEOUT_SECONDS)])
        self.assertEqual(chat_stream.deleted_sessions, ["session-1"])
        self.assertEqual(handler.server.state.chat_session.get("sessionId"), "")
        close_chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()

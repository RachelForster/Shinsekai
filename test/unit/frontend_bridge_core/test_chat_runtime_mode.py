import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from application.chat.runtime_process import (
    _chat_runtime_mode,
    _chat_runtime_status,
    _chat_snapshot,
    _chat_stream_initial_snapshot,
)
from frontend_bridge_core.routes.api import BRIDGE_AUTH_HEADER, CHAT_RUNTIME_READY_TIMEOUT_SECONDS, FrontendBridgeHandler
from application.chat.templates import _history_id_from_scenario


class _SystemConfig:
    live_room_id = ""
    voice_language = "ja"
    chat_ui_runtime_mode = "react"
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

    def get_character_by_name(self, name: str):
        name_key = name.lower()
        return next(
            (character for character in self.config.characters if character.name.lower() == name_key),
            None,
        )

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
        self.snapshot_renderer_ids = []
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

    def get_snapshot(self, session_id: str, *, renderer_id: str = ""):
        self.snapshot_renderer_ids.append(renderer_id)
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
    def test_chat_snapshot_registers_polling_renderer_with_stream(self):
        chat_stream = _ChatStreamStub()
        chat_stream.snapshots["session-1"] = {
            "dialogText": "speaking",
            "inputDraft": "",
            "options": [],
            "sessionId": "session-1",
            "sprites": [],
            "status": "speaking",
        }
        state = SimpleNamespace(
            chat_runtime_closing=False,
            chat_session={"sessionId": "session-1"},
            chat_stream=chat_stream,
            config_manager=_ConfigManager(),
            mobile_access_service=None,
        )

        snapshot = _chat_snapshot(state, renderer_id="renderer-polling")

        self.assertEqual(snapshot["dialogText"], "speaking")
        self.assertEqual(chat_stream.snapshot_renderer_ids[0], "renderer-polling")

    def test_stream_initial_snapshot_drops_previous_session_sprites(self):
        previous = {
            "characterName": "七海千秋",
            "dialogText": "keep dialog",
            "inputDraft": "keep draft",
            "options": ["keep option"],
            "sprites": [{"id": "江之岛盾子-0", "label": "江之岛盾子", "path": "junko.png"}],
            "status": "idle",
        }

        initial = _chat_stream_initial_snapshot(previous)

        self.assertEqual(initial["sprites"], [])
        self.assertEqual(initial["characterName"], "七海千秋")
        self.assertEqual(initial["dialogText"], "keep dialog")
        self.assertEqual(initial["inputDraft"], "keep draft")
        self.assertEqual(initial["options"], ["keep option"])
        self.assertEqual(previous["sprites"], [{"id": "江之岛盾子-0", "label": "江之岛盾子", "path": "junko.png"}])
        self.assertEqual(previous["sprites"][0]["label"], "江之岛盾子")

    def test_chat_runtime_mode_defaults_to_react(self):
        state = SimpleNamespace(config_manager=_ConfigManager())

        self.assertEqual(_chat_runtime_mode(state), "react")

    def test_chat_runtime_mode_ignores_legacy_native_config(self):
        state = SimpleNamespace(config_manager=_ConfigManager())
        state.config_manager.config.system_config.chat_ui_runtime_mode = "native"

        self.assertEqual(_chat_runtime_mode(state), "react")

    def test_chat_runtime_status_reports_idle_without_building_snapshot(self):
        state = SimpleNamespace(chat_runtime_closing=False)

        with patch("application.chat.runtime_process._chat_process_running", return_value=False):
            status = _chat_runtime_status(state)

        self.assertEqual(
            status,
            {
                "state": "idle",
                "chatProcessRunning": False,
                "chatRuntimeClosing": False,
            },
        )

    def test_chat_runtime_status_reports_running(self):
        state = SimpleNamespace(chat_runtime_closing=False)

        with patch("application.chat.runtime_process._chat_process_running", return_value=True):
            status = _chat_runtime_status(state)

        self.assertEqual(status["state"], "running")
        self.assertTrue(status["chatProcessRunning"])
        self.assertFalse(status["chatRuntimeClosing"])

    def test_chat_runtime_status_prioritizes_closing_over_running(self):
        state = SimpleNamespace(chat_runtime_closing=True)

        with patch("application.chat.runtime_process._chat_process_running", return_value=True):
            status = _chat_runtime_status(state)

        self.assertEqual(status["state"], "closing")
        self.assertTrue(status["chatProcessRunning"])
        self.assertTrue(status["chatRuntimeClosing"])

    def test_chat_runtime_status_observes_close_that_starts_as_process_exits(self):
        state = SimpleNamespace(chat_runtime_closing=False)

        def process_exits_during_close():
            state.chat_runtime_closing = True
            return False

        with patch(
            "application.chat.runtime_process._chat_process_running",
            side_effect=process_exits_during_close,
        ):
            status = _chat_runtime_status(state)

        self.assertEqual(status["state"], "closing")
        self.assertFalse(status["chatProcessRunning"])
        self.assertTrue(status["chatRuntimeClosing"])

    def test_runtime_status_route_does_not_build_chat_snapshot(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        handler.path = "/api/chat/runtime-status"
        handler.server = SimpleNamespace(state=SimpleNamespace(chat_runtime_closing=False))
        responses = []
        handler._send_json = lambda payload, status=None: responses.append(payload)

        with (
            patch("application.chat.runtime_process._chat_process_running", return_value=False),
            patch(
                "frontend_bridge_core.routes.api._chat_snapshot",
                side_effect=AssertionError("runtime status must not build a chat snapshot"),
            ),
        ):
            handler.do_GET()

        self.assertEqual(
            responses,
            [
                {
                    "state": "idle",
                    "chatProcessRunning": False,
                    "chatRuntimeClosing": False,
                }
            ],
        )

    def test_chat_snapshot_includes_runtime_mode(self):
        state = SimpleNamespace(
            chat_session={},
            chat_stream=None,
            config_manager=_ConfigManager(),
        )
        state.config_manager.config.system_config.chat_ui_runtime_mode = "native"

        snapshot = _chat_snapshot(state, "idle", "react started")

        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertEqual(snapshot["dialogText"], "react started")

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

    def test_mobile_write_requests_allow_only_the_same_http_origin(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        handler.path = "/api/chat/command"
        handler.server = SimpleNamespace(state=SimpleNamespace(auth_token="secret"))
        handler.headers = {
            "Host": "192.168.1.20:8789",
            "Origin": "http://192.168.1.20:8789",
            BRIDGE_AUTH_HEADER: "secret",
        }

        handler._require_authorized_write("/api/chat/command")

        handler.headers["Origin"] = "http://192.168.1.21:8789"
        with self.assertRaisesRegex(PermissionError, "request origin is not allowed"):
            handler._require_authorized_write("/api/chat/command")

    def test_remote_read_requests_require_header_query_or_cookie_token(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        handler.path = "/api/chat/snapshot"
        handler.client_address = ("192.168.1.30", 51000)
        handler.server = SimpleNamespace(state=SimpleNamespace(auth_token="secret"))
        handler.headers = {}

        with self.assertRaisesRegex(PermissionError, "invalid bridge auth token"):
            handler._require_authorized_read("/api/chat/snapshot")

        handler.path = "/api/chat/snapshot?shinsekai_bridge_token=secret"
        handler._require_authorized_read("/api/chat/snapshot")

        handler.path = "/api/chat/snapshot"
        handler.headers = {"Cookie": "shinsekai_bridge_token=secret"}
        handler._require_authorized_read("/api/chat/snapshot")

    def test_remote_data_reads_require_bridge_auth_token(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        handler.path = "/data/config/api.yaml"
        handler.client_address = ("192.168.1.30", 51000)
        handler.server = SimpleNamespace(state=SimpleNamespace(auth_token="secret"))
        handler.headers = {}

        with self.assertRaisesRegex(PermissionError, "invalid bridge auth token"):
            handler._require_authorized_read("/data/config/api.yaml")
        with self.assertRaisesRegex(PermissionError, "invalid bridge auth token"):
            handler._require_authorized_read("/assets/../data/config/api.yaml")

        handler.path = "/data/config/api.yaml?shinsekai_bridge_token=secret"
        handler._require_authorized_read("/data/config/api.yaml")

        handler.path = "/data/config/api.yaml"
        handler.client_address = ("127.0.0.1", 51000)
        handler.headers = {}
        handler._require_authorized_read("/data/config/api.yaml")

    def test_launch_chat_forces_legacy_native_config_to_react(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "native"
        config_manager.config.effect_list = [
            SimpleNamespace(
                name="Ambient",
                audio_list=["impact.wav", "unused.wav", "notice.wav"],
                audio_tags="Effect 1：impact\n\nEffect 3：notice\n",
            )
        ]

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
                "effectNames": ["Ambient"],
                "scenario": "scene",
                "system": "system",
                "templateId": "native-template",
                "templateName": "Native Template",
            }

            with patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat, patch(
                "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ):
                snapshot = handler._launch_chat(body)

        self.assertEqual(len(chat_stream.create_session_calls), 1)
        self.assertEqual(
            launch_chat.call_args.kwargs["stream_endpoint"],
            "ws://127.0.0.1:8788/ws?sessionId=session-1&role=producer",
        )
        self.assertEqual(launch_chat.call_args.kwargs["init_stream_endpoint"], "")
        self.assertEqual(launch_chat.call_args.kwargs["effect_names"], "Ambient")
        self.assertIn("- impact", launch_chat.call_args.kwargs["system_template"])
        self.assertIn("- notice", launch_chat.call_args.kwargs["system_template"])
        self.assertEqual(
            launch_chat.call_args.kwargs["system_template"].count("- impact"),
            1,
        )
        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertEqual(snapshot["sessionId"], "session-1")

    @unittest.skipUnless(os.name == "nt", "Windows drive semantics")
    def test_launch_chat_allows_history_on_a_different_drive(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "native"
        state = SimpleNamespace(
            chat_session={},
            chat_stream=None,
            config_manager=config_manager,
            history_dir=r"C:\project\data\chat_history",
            project_root_dir=r"C:\project",
            template_dir_path=r"C:\project\data\character_templates",
        )
        handler.server = SimpleNamespace(state=state)
        body = {
            "historyPath": r"D:\external-history\session.json",
            "scenario": "scene",
            "system": "system",
            "templateId": "cross-drive-template",
            "templateName": "Cross Drive",
        }

        with (
            patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False),
            patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat,
            patch(
                "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ),
        ):
            snapshot = handler._launch_chat(body)

        self.assertEqual(
            launch_chat.call_args.kwargs["history_file"],
            "D:/external-history/session",
        )
        self.assertEqual(snapshot["historyPath"], "D:/external-history/session")

    def test_launch_chat_normalizes_stale_characters_before_runtime_inputs(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.characters = [
            SimpleNamespace(
                name="Alice",
                sprites=[SimpleNamespace(path="sprites/alice.png")],
            ),
        ]

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
                "characters": ["Deleted", " alice "],
                "initSpritePath": "",
                "scenario": "restored scene",
                "system": "generated system",
                "templateId": "restored-template",
                "templateName": "Restored Template",
            }

            with patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat, patch(
                "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ):
                snapshot = handler._launch_chat(body)

        runtime_args = launch_chat.call_args.kwargs
        self.assertEqual(runtime_args["character_names"], ["Alice"])
        self.assertEqual(runtime_args["init_sprite_path"], "sprites/alice.png")
        self.assertEqual(
            Path(runtime_args["history_file"]).name,
            _history_id_from_scenario("restored scene", ["Alice"]),
        )
        self.assertEqual(handler.server.state.chat_session["characterName"], "Alice")
        self.assertEqual(snapshot["characterName"], "Alice")

    def test_direct_quick_restart_persists_new_managed_history_without_changing_scenario(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        config_manager = _ConfigManager()
        config_manager.config.characters = [
            SimpleNamespace(name="Alice", sprites=[SimpleNamespace(path="sprites/alice.png")]),
        ]

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            history_dir.mkdir()
            template_dir = root / "templates"
            template_dir.mkdir()
            previous_history = history_dir / _history_id_from_scenario("scene", ["Alice"])
            previous_history.mkdir()
            marker = previous_history / "active.json"
            marker.write_text("previous", encoding="utf-8")
            handler.server = SimpleNamespace(
                state=SimpleNamespace(
                    chat_session={},
                    chat_stream=_ChatStreamStub(),
                    config_manager=config_manager,
                    history_dir=str(history_dir),
                    template_dir_path=str(template_dir),
                )
            )
            body = {
                "characters": ["Alice"],
                "historyPath": previous_history.as_posix(),
                "resetHistory": True,
                "scenario": "scene",
                "system": "system",
                "templateId": "template",
                "templateName": "Template",
            }
            instance_id = "20260830T204500123456Z-a1b2c3d4"

            with (
                patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False),
                patch("frontend_bridge_core.routes.api._launch_chat", return_value="聊天进程已启动！PID: 12345") as launch_chat,
                patch(
                    "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                    side_effect=lambda _state, scenario, system: (scenario, system),
                ),
                patch(
                    "application.chat.launch_history._new_history_instance_id",
                    return_value=instance_id,
                ),
                patch(
                    "frontend_bridge_core.routes.api.persist_confirmed_history_path",
                    return_value=True,
                ) as persist_history_path,
            ):
                snapshot = handler._launch_chat(body)
            marker_survived = marker.is_file()

        expected_history = f"{_history_id_from_scenario('scene', ['Alice'])}-{instance_id}"
        self.assertEqual(launch_chat.call_args.kwargs["user_scenario"], "scene")
        self.assertEqual(
            Path(launch_chat.call_args.kwargs["history_file"]).name,
            expected_history,
        )
        self.assertEqual(Path(snapshot["historyPath"]).name, expected_history)
        persist_history_path.assert_called_once_with(
            handler.server.state,
            Path(snapshot["historyPath"]),
        )
        self.assertTrue(marker_survived)

    def test_quick_restart_does_not_select_a_new_history_while_runtime_is_busy(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        config_manager = _ConfigManager()
        config_manager.config.characters = [SimpleNamespace(name="Alice", sprites=[])]

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            root = Path(tmp_dir)
            history_dir = root / "history"
            history_dir.mkdir()
            template_dir = root / "templates"
            template_dir.mkdir()
            current_history = history_dir / "current"
            handler.server = SimpleNamespace(
                state=SimpleNamespace(
                    chat_session={
                        "characterName": "Alice",
                        "historyPath": current_history.as_posix(),
                        "sessionId": "",
                    },
                    chat_stream=None,
                    config_manager=config_manager,
                    history_dir=str(history_dir),
                    mobile_access_service=None,
                    template_dir_path=str(template_dir),
                )
            )
            body = {
                "characters": ["Alice"],
                "resetHistory": True,
                "scenario": "scene",
                "system": "system",
                "templateId": "template",
                "templateName": "Template",
            }

            with (
                patch("frontend_bridge_core.routes.api._chat_process_running", return_value=True),
                patch("frontend_bridge_core.routes.api.plan_chat_history_launch") as plan_history,
                patch("frontend_bridge_core.routes.api.clear_story_session") as clear_story,
            ):
                snapshot = handler._launch_chat(body)

        plan_history.assert_not_called()
        clear_story.assert_not_called()
        self.assertEqual(snapshot["historyPath"], current_history.as_posix())
        self.assertEqual(
            handler.server.state.chat_session["historyPath"],
            current_history.as_posix(),
        )

    def test_legacy_native_async_init_uses_react_stream_session(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "native"
        init_stream_info = chat_stream.create_session({})
        chat_stream.create_session_calls.clear()

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
                "templateId": "native-init-template",
                "templateName": "Native Init Template",
            }

            with patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="chat process started; PID: 12345",
            ) as launch_chat, patch(
                "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ):
                snapshot = handler._launch_chat(body, init_stream_info=init_stream_info)

        self.assertEqual(chat_stream.create_session_calls, [])
        self.assertEqual(
            launch_chat.call_args.kwargs["stream_endpoint"],
            init_stream_info["producerEndpoint"],
        )
        self.assertEqual(launch_chat.call_args.kwargs["init_stream_endpoint"], "")
        self.assertEqual(chat_stream.wait_calls, [("session-1", CHAT_RUNTIME_READY_TIMEOUT_SECONDS)])
        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertTrue(snapshot["_chatInitStreamAttached"])
        self.assertEqual(snapshot["sessionId"], "session-1")
        self.assertEqual(handler.server.state.chat_session["sessionId"], "session-1")

    def test_resume_last_chat_creates_stream_session_in_react_mode(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        chat_stream = _ChatStreamStub()
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "react"
        config_manager.config.characters = [
            SimpleNamespace(
                name="Alice",
                sprites=[SimpleNamespace(path="sprites/alice.png")],
            ),
        ]

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
                "frontend_bridge_core.routes.api._load_template_session_payload",
                return_value={
                    "background": "",
                    "historyPath": history_path.relative_to(Path.cwd()).as_posix(),
                    "initSpritePath": "",
                    "roomId": "",
                    "scenario": "scene",
                    "selectedCharacters": ["Deleted", "Alice"],
                    "system": "system",
                    "templateFileDropdown": "resume-template",
                    "voiceLanguage": "ja",
                },
            ), patch(
                "frontend_bridge_core.routes.api._resume_template_parts",
                return_value=("scene", "system", "resume-template"),
            ), patch(
                "frontend_bridge_core.routes.api._chat_process_running",
                return_value=False,
            ), patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat:
                snapshot = handler._resume_last_chat()

        self.assertEqual(len(chat_stream.create_session_calls), 1)
        self.assertEqual(chat_stream.create_session_calls[0]["sprites"], [])
        self.assertEqual(chat_stream.create_session_calls[0]["runtimeMode"], "react")
        self.assertEqual(chat_stream.create_session_calls[0]["status"], "idle")
        self.assertEqual(chat_stream.wait_calls, [("session-1", CHAT_RUNTIME_READY_TIMEOUT_SECONDS)])
        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertEqual(snapshot["sessionId"], "session-1")
        self.assertEqual(launch_chat.call_args.kwargs["character_names"], ["Alice"])
        self.assertEqual(launch_chat.call_args.kwargs["init_sprite_path"], "sprites/alice.png")
        self.assertEqual(handler.server.state.chat_session["characterName"], "Alice")

    @unittest.skipUnless(os.name == "nt", "Windows drive semantics")
    def test_resume_last_chat_allows_history_on_a_different_drive(self):
        handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
        config_manager = _ConfigManager()
        config_manager.config.system_config.chat_ui_runtime_mode = "native"
        handler.server = SimpleNamespace(
            state=SimpleNamespace(
                chat_session={},
                chat_stream=None,
                config_manager=config_manager,
                history_dir=r"C:\project\data\chat_history",
                project_root_dir=r"C:\project",
                template_dir_path=r"C:\project\data\character_templates",
            )
        )

        with (
            patch(
                "frontend_bridge_core.routes.api._load_template_session_payload",
                return_value={
                    "background": "",
                    "historyPath": r"D:\external-history\resume.json",
                    "roomId": "",
                    "scenario": "scene",
                    "selectedCharacters": [],
                    "system": "system",
                    "templateFileDropdown": "resume-template",
                    "voiceLanguage": "ja",
                },
            ),
            patch(
                "frontend_bridge_core.routes.api._resume_template_parts",
                return_value=("scene", "system", "resume-template"),
            ),
            patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False),
            patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat,
        ):
            snapshot = handler._resume_last_chat()

        self.assertEqual(
            launch_chat.call_args.kwargs["history_file"],
            "D:/external-history/resume",
        )
        self.assertEqual(snapshot["historyPath"], "D:/external-history/resume")

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

            with patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ), patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ) as launch_chat:
                snapshot = handler._launch_chat(body)

        self.assertEqual(snapshot["runtimeMode"], "react")
        self.assertEqual(snapshot["sessionId"], "session-1")
        self.assertEqual(chat_stream.create_session_calls[0]["sprites"], [])
        self.assertEqual(chat_stream.create_session_calls[0]["runtimeMode"], "react")
        self.assertEqual(chat_stream.create_session_calls[0]["status"], "idle")
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

            with patch("frontend_bridge_core.routes.api._chat_process_running", return_value=False), patch(
                "frontend_bridge_core.routes.api._repair_template_parts_from_session_if_needed",
                side_effect=lambda _state, scenario, system: (scenario, system),
            ), patch(
                "frontend_bridge_core.routes.api._launch_chat",
                return_value="聊天进程已启动！PID: 12345",
            ), patch(
                "frontend_bridge_core.routes.api.stop_chat",
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

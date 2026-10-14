"""Prepare templates, configuration and a trusted child launch plan."""

from __future__ import annotations
from typing import Any
from pathlib import Path
from collections.abc import Callable
import json
import os
import sys
from application.chat.runtime_ports import LaunchPlan, LaunchRejected
from application.chat.build_effect_context import SelectedEffectContext
from application.chat.templates import (
    TEMP_SPLIT_META,
    _compose_runtime_template,
    _effective_user_scenario,
    _history_id_from_scenario,
    _template_dir,
)
from application.chat.history_paths import is_unc_history_path
from application.chat.launch_args import CHAT_LAUNCH_CONFIG_ENV
from core.chat_history.storage import chat_history_session_dir
from core.media.chat_attachments import CHAT_ATTACHMENTS_ROOT_ENV


class ChatLaunchPreparation:
    def __init__(
        self,
        *,
        project_root: Callable[[], Path],
        app_root: Callable[[Any], Path],
        exe_candidates: Callable[[Any], list[Path]],
        main_py: Callable[[], Path],
    ) -> None:
        self.project_root, self.app_root = project_root, app_root
        self.exe_candidates, self.main_py = exe_candidates, main_py

    def prepare(
        self,
        state: Any,
        *,
        character_names: list[str] | None = None,
        effect_names: str = "",
        effect_context: SelectedEffectContext | None = None,
        history_file: str,
        init_sprite_path: str,
        show_initial_sprite: bool = True,
        room_id: str,
        selected_bg: str,
        system_template: str,
        use_cg: bool,
        user_scenario: str,
        stream_endpoint: str = "",
        init_stream_endpoint: str = "",
        workflow_path: str = "",
        media_selection_mode: str = "indexed",
        use_current_template_for_history: bool = False,
    ) -> LaunchPlan | LaunchRejected:
        effective_user_scenario = _effective_user_scenario(user_scenario)
        chat_session = getattr(state, "chat_session", {}) or {}
        player_name = str(chat_session.get("playerCharacter") or "")
        read_player_speech = bool(chat_session.get("readPlayerSpeech", False))
        from ai.llm.template.dialog.sections.player import player_runtime_prompt

        player_rules = player_runtime_prompt(
            state.config_manager,
            player_name,
            allow_dialogue=bool(chat_session.get("allowPlayerDialogue", True)),
            read_speech=read_player_speech,
            media_selection_mode=media_selection_mode,
        )
        template = _compose_runtime_template(
            (system_template or "") + ("\n" + player_rules if player_rules else ""),
            effective_user_scenario,
            effect_context,
        )
        template_dir = _template_dir(state)
        (template_dir / "_temp.txt").write_text(template, encoding="utf-8")
        (template_dir / TEMP_SPLIT_META).write_text(
            json.dumps(
                {"scenario": effective_user_scenario, "system": system_template},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        sc = state.config_manager.config.system_config.model_copy(deep=True)
        sc.live_room_id = room_id
        state.config_manager.config.system_config = sc
        state.config_manager.save_system_config()
        template_hash = _history_id_from_scenario(user_scenario, character_names)
        history_path = (
            Path(history_file)
            if history_file
            else Path(state.history_dir) / template_hash
        )
        history_argument = str(history_path)
        if not is_unc_history_path(history_path):
            if (
                history_path.suffix.lower() == ".json"
                and history_path.exists()
                and history_path.is_file()
            ):
                history_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                chat_history_session_dir(history_path).mkdir(
                    parents=True, exist_ok=True
                )
            history_argument = str(history_path.resolve())
        project_root = self.project_root()
        app_root = self.app_root(state)
        tts_slug = (
            str(
                state.config_manager.config.api_config.tts_provider or "gpt-sovits"
            ).strip()
            or "gpt-sovits"
        )
        launch_config = {
            "template": "_temp",
            "init_sprite_path": init_sprite_path or "",
            "show_initial_sprite": show_initial_sprite,
            "history": history_argument,
            "bg": selected_bg,
            "effect_names": effect_names,
            "t2i": "ComfyUI" if use_cg else "",
            "room_id": room_id,
            "tts": tts_slug,
            "media_selection_mode": (
                "semantic" if media_selection_mode == "semantic" else "indexed"
            ),
        }
        if character_names:
            launch_config["characters"] = json.dumps(
                character_names, ensure_ascii=False
            )
        if player_name:
            launch_config["player_character"] = player_name
            launch_config["read_player_speech"] = read_player_speech
            launch_config["allow_player_dialogue"] = bool(
                chat_session.get("allowPlayerDialogue", True)
            )
        if stream_endpoint:
            launch_config["stream_endpoint"] = stream_endpoint
        if init_stream_endpoint:
            launch_config["init_stream_endpoint"] = init_stream_endpoint
        if workflow_path:
            launch_config["workflow"] = workflow_path
        env = os.environ.copy()
        if use_current_template_for_history or player_name:
            launch_config["use_current_template_for_history"] = True
        env[CHAT_LAUNCH_CONFIG_ENV] = json.dumps(launch_config, ensure_ascii=False)
        env["SHINSEKAI_PROJECT_ROOT"] = str(project_root)
        env["EASYAI_PROJECT_ROOT"] = str(project_root)
        env["SHINSEKAI_APP_ROOT"] = str(app_root)
        attachment_root = os.environ.get(CHAT_ATTACHMENTS_ROOT_ENV, "").strip() or str(
            project_root
        )
        os.environ.setdefault(CHAT_ATTACHMENTS_ROOT_ENV, attachment_root)
        env[CHAT_ATTACHMENTS_ROOT_ENV] = attachment_root
        env["SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG"] = "1"
        api_config = state.config_manager.config.api_config
        env["SHINSEKAI_MEMORY_AUTO_ENABLED"] = (
            "1" if bool(getattr(api_config, "memory_auto_enabled", False)) else "0"
        )
        env["SHINSEKAI_MEMORY_EXTRACT_INTERVAL_TURNS"] = str(
            max(1, int(getattr(api_config, "memory_extract_interval_turns", 5) or 5))
        )
        env["SHINSEKAI_MEMORY_SEARCH_LIMIT"] = str(
            max(1, int(getattr(api_config, "memory_search_limit", 5) or 5))
        )
        env["SHINSEKAI_MEMORY_RECENT_BUFFER_MESSAGES"] = str(
            max(2, int(getattr(api_config, "memory_recent_buffer_messages", 16) or 16))
        )
        chat_stream = getattr(state, "chat_stream", None)
        memory_service_base = str(getattr(chat_stream, "http_base", "") or "").strip()
        if memory_service_base:
            env["SHINSEKAI_MEMORY_SERVICE_URL"] = (
                f"{memory_service_base.rstrip('/')}/api/memory"
            )
            env["SHINSEKAI_MEMORY_SERVICE_OWNER"] = "0"
        if str(getattr(state, "auth_token", "") or "").strip():
            env["SHINSEKAI_MEMORY_SERVICE_TOKEN"] = str(state.auth_token)
        if getattr(sys, "frozen", False):
            candidates = self.exe_candidates(state)
            exe = next((item for item in candidates if item.is_file()), None)
            if exe is None:
                checked = " 与 ".join((str(item) for item in candidates))
                return LaunchRejected(
                    f"启动失败: 未找到 main.exe（已检查 {checked}）。"
                )
            command = [str(exe)]
        else:
            main_py = self.main_py()
            if not main_py.is_file():
                return LaunchRejected(f"启动失败: 未找到 main.py（已检查 {main_py}）。")
            command = [sys.executable, str(main_py)]
        return LaunchPlan(command=command, cwd=project_root, environment=env)

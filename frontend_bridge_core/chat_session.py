from __future__ import annotations

from typing import Any

from application.chat.initialization import start_chat_init
from application.chat.mobile_access import configure_mobile_access
from application.chat.runtime_process import (
    TRANSPARENT_BACKGROUND_NAME,
    _chat_history_path,
    _chat_process_running,
    _chat_runtime_closing,
    _chat_runtime_mode,
    _chat_snapshot,
    _chat_stream_initial_snapshot,
    _close_chat,
    _launch_chat as _launch_runtime_chat,
    _sanitize_user_display_name,
    remove_chat_history_storage,
)
from application.chat.templates import (
    _compose_for_llm,
    _latest_history_json,
    _list_templates,
    _load_template_session_payload,
    _repair_template_parts_from_session_if_needed,
    _resolve_template_character_names,
    _resume_template_parts,
    _scenario_from_template_like,
    initial_sprite_path_for_characters,
)
from application.runtime.dependencies import runtime_dependency_error_from_text
from application.runtime.state import BridgeState
from frontend_bridge_core.effects import _build_effect_usage_guide

CHAT_RUNTIME_READY_TIMEOUT_SECONDS = 20.0


def wait_for_chat_runtime_ready(
    state: BridgeState,
    stream_info: dict[str, Any],
    *,
    timeout: float = CHAT_RUNTIME_READY_TIMEOUT_SECONDS,
) -> None:
    session_id = str(stream_info.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if not session_id or chat_stream is None:
        return
    wait_for_producer = getattr(chat_stream, "wait_for_producer", None)
    if wait_for_producer is None:
        return
    if wait_for_producer(session_id, timeout=timeout):
        return
    try:
        _close_chat(state, reason="聊天会话启动超时。")
    finally:
        chat_stream.delete_session(session_id)
        state.chat_session = {**state.chat_session, "sessionId": ""}
    raise RuntimeError("启动失败: 实时聊天会话未就绪，请稍后重试。")


def start_chat_initialization(
    state: BridgeState,
    body: dict[str, Any],
) -> dict[str, Any]:
    mode = str(body.get("mode") or "").strip().lower()
    if mode == "launch":
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object when mode is 'launch'")

        def launch_request(stream_info: dict[str, str]) -> dict[str, Any]:
            return launch_chat(state, payload, init_stream_info=stream_info)

        launch = launch_request
    elif mode == "resume-last":

        def resume_request(stream_info: dict[str, str]) -> dict[str, Any]:
            return resume_last_chat(state, init_stream_info=stream_info)

        launch = resume_request
    else:
        raise ValueError("mode must be 'launch' or 'resume-last'")
    return start_chat_init(state, mode=mode, launch=launch)


def launch_chat(
    state: BridgeState,
    body: dict[str, Any],
    *,
    init_stream_info: dict[str, str] | None = None,
) -> dict[str, Any]:
    if _chat_runtime_closing(state):
        raise RuntimeError("聊天会话正在关闭，请稍后再启动。")
    mobile_access_enabled = bool(body.get("enableMobileAccess", False))
    if not mobile_access_enabled:
        configure_mobile_access(state, enabled=False)
    template_id = str(body.get("templateId") or "")
    rows = _list_templates(state)
    row = next((item for item in rows if item["id"] == template_id), None)
    has_inline_template = "scenario" in body or "system" in body
    if has_inline_template:
        scenario = str(body.get("scenario") or "")
        system_template = str(body.get("system") or "")
        row = {
            "content": _compose_for_llm(scenario, system_template),
            "id": template_id or "_temp.txt",
            "name": str(body.get("templateName") or template_id or "_temp"),
            "scenario": scenario,
            "system": system_template,
        }
    elif row is None:
        raise KeyError(f"template not found: {template_id}")
    characters = _resolve_template_character_names(
        state,
        body.get("characters") or [],
    )
    first_character = characters[0] if characters else ""
    init_sprite_path = initial_sprite_path_for_characters(
        state.config_manager,
        str(body.get("initSpritePath") or ""),
        characters,
    )
    room_id = str(
        body.get("roomId")
        or state.config_manager.config.system_config.live_room_id
        or ""
    )
    normalized_history_payload = {**body, "characters": characters}
    history_path = _chat_history_path(state, normalized_history_payload, row)
    default_history_path = _chat_history_path(
        state,
        {"historyPath": "", "characters": characters},
        row,
    )
    reset_history = bool(body.get("resetHistory"))
    if reset_history:
        for item in {history_path, default_history_path}:
            remove_chat_history_storage(item)
    user_scenario = _scenario_from_template_like(row)
    system_template = str(row.get("system") or "")
    user_scenario, system_template = _repair_template_parts_from_session_if_needed(
        state,
        user_scenario,
        system_template,
    )
    user_display_name = _sanitize_user_display_name(body.get("userDisplayName"))
    active_history_path = default_history_path if reset_history else history_path
    session_base = {
        "backgroundName": str(body.get("backgroundName") or ""),
        "characterName": first_character,
        "historyPath": active_history_path.as_posix(),
        "sessionId": "",
        "templateId": template_id,
        "userDisplayName": user_display_name,
        "voiceLanguage": str(
            state.config_manager.config.system_config.voice_language or "ja"
        ),
        "workflowPath": str(body.get("workflowPath") or ""),
    }
    if _chat_process_running():
        state.chat_session = {**state.chat_session, **session_base}
        configure_mobile_access(
            state,
            enabled=mobile_access_enabled,
        )
        return _chat_snapshot(
            state,
            None,
            "",
            extra={"statusMessage": "进程已经在运行中。"},
        )
    state.chat_session = {**state.chat_session, **session_base}
    initial_snapshot = _chat_stream_initial_snapshot(_chat_snapshot(state, "idle", ""))
    use_react_runtime = _chat_runtime_mode(state) == "react"
    stream_info = init_stream_info or (
        state.chat_stream.create_session(initial_snapshot)
        if use_react_runtime and state.chat_stream is not None
        else {}
    )
    effect_names_list = body.get("effectNames") or []
    if isinstance(effect_names_list, list):
        effect_names_str = ",".join(str(name) for name in effect_names_list)
    else:
        effect_names_str = ""
    effect_guide = _build_effect_usage_guide(
        state,
        effect_names_list if isinstance(effect_names_list, list) else [],
    )
    if effect_guide:
        system_template = system_template.rstrip() + "\n\n" + effect_guide
    message = _launch_runtime_chat(
        state,
        character_names=characters,
        effect_names=effect_names_str,
        history_file=active_history_path.as_posix(),
        init_sprite_path=init_sprite_path,
        room_id=room_id,
        selected_bg=str(body.get("backgroundName") or ""),
        system_template=system_template,
        use_cg=bool(body.get("useCg")),
        user_scenario=user_scenario,
        stream_endpoint=(
            str(stream_info.get("producerEndpoint") or "") if use_react_runtime else ""
        ),
        init_stream_endpoint=(
            str(stream_info.get("producerEndpoint") or "")
            if not use_react_runtime
            else ""
        ),
        workflow_path=str(body.get("workflowPath") or ""),
    )
    dependency_error = runtime_dependency_error_from_text(message)
    if dependency_error:
        session_id = str(stream_info.get("sessionId") or "")
        if session_id and state.chat_stream is not None:
            state.chat_stream.delete_session(session_id)
        state.chat_session = {**state.chat_session, **session_base}
        return _chat_snapshot(
            state,
            "error",
            message,
            extra={"runtimeDependencyError": dependency_error},
        )
    if message.startswith("启动失败"):
        session_id = str(stream_info.get("sessionId") or "")
        if session_id and state.chat_stream is not None:
            state.chat_stream.delete_session(session_id)
        raise RuntimeError(message)
    state.chat_session = {
        **state.chat_session,
        **session_base,
        "sessionId": (
            str(stream_info.get("sessionId") or "") if use_react_runtime else ""
        ),
    }
    if (
        use_react_runtime
        and stream_info.get("sessionId")
        and state.chat_stream is not None
    ):
        state.chat_stream.update_session_snapshot(
            str(stream_info["sessionId"]),
            {
                "backgroundPath": _chat_snapshot(state).get("backgroundPath", ""),
                "characterName": first_character,
                "dialogText": "",
                "historyPath": active_history_path.as_posix(),
                "status": "idle",
                "statusMessage": message,
                "userDisplayName": user_display_name,
                "voiceLanguage": str(state.chat_session.get("voiceLanguage") or "ja"),
            },
        )
        wait_for_chat_runtime_ready(state, stream_info)
    configure_mobile_access(
        state,
        enabled=mobile_access_enabled,
    )
    return _chat_snapshot(
        state,
        "idle",
        "",
        extra={
            "statusMessage": message,
            **({"_chatInitStreamAttached": True} if init_stream_info else {}),
        },
    )


def resume_last_chat(
    state: BridgeState,
    *,
    init_stream_info: dict[str, str] | None = None,
) -> dict[str, Any]:
    if _chat_runtime_closing(state):
        raise RuntimeError("聊天会话正在关闭，请稍后再启动。")
    session = _load_template_session_payload(state) or {}
    mobile_access_enabled = bool(session.get("enableMobileAccess", False))
    if not mobile_access_enabled:
        configure_mobile_access(state, enabled=False)
    session_history_path = str(session.get("historyPath") or "").strip()
    history_path = (
        _chat_history_path(state, {"historyPath": session_history_path}, session)
        if session_history_path
        else _latest_history_json(state.history_dir)
    )
    if history_path is None:
        raise FileNotFoundError("未找到聊天记录（*.json）。请先在主窗口进行过对话。")
    template_parts = _resume_template_parts(state)
    session_scenario = str(session.get("scenario") or "")
    session_system = str(session.get("system") or "")
    if session_scenario.strip() or session_system.strip():
        template_parts = (
            session_scenario,
            session_system,
            str(session.get("templateFileDropdown") or "_temp.txt"),
        )
    if template_parts is None:
        raise FileNotFoundError(
            "未找到可用模板（.txt）。请先在聊天模板页生成、保存或启动过一次。"
        )
    scenario, system_template, template_id = template_parts
    selected_characters = _resolve_template_character_names(
        state,
        session.get("selectedCharacters") or [],
    )
    first_character = selected_characters[0] if selected_characters else ""
    init_sprite_path = initial_sprite_path_for_characters(
        state.config_manager,
        str(session.get("initSpritePath") or ""),
        selected_characters,
    )
    room_id = str(
        session.get("roomId")
        or state.config_manager.config.system_config.live_room_id
        or ""
    )
    selected_bg = str(session.get("background") or TRANSPARENT_BACKGROUND_NAME)
    user_display_name = _sanitize_user_display_name(session.get("userDisplayName"))
    session_base = {
        "backgroundName": selected_bg,
        "characterName": first_character,
        "historyPath": history_path.as_posix(),
        "sessionId": "",
        "templateId": template_id,
        "userDisplayName": user_display_name,
        "voiceLanguage": str(
            session.get("voiceLanguage")
            or state.config_manager.config.system_config.voice_language
            or "ja"
        ),
        "workflowPath": str(session.get("workflowPath") or ""),
    }
    if _chat_process_running():
        state.chat_session = {**state.chat_session, **session_base}
        configure_mobile_access(
            state,
            enabled=mobile_access_enabled,
        )
        return _chat_snapshot(
            state,
            None,
            "",
            extra={"statusMessage": "进程已经在运行中。"},
        )
    state.chat_session = {**state.chat_session, **session_base}
    initial_snapshot = _chat_stream_initial_snapshot(_chat_snapshot(state, "idle", ""))
    use_react_runtime = _chat_runtime_mode(state) == "react"
    stream_info = init_stream_info or (
        state.chat_stream.create_session(initial_snapshot)
        if use_react_runtime and state.chat_stream is not None
        else {}
    )
    message = _launch_runtime_chat(
        state,
        character_names=selected_characters,
        history_file=history_path.as_posix(),
        init_sprite_path=init_sprite_path,
        room_id=room_id,
        selected_bg=selected_bg,
        system_template=system_template,
        use_cg=bool(session.get("useCg", False)),
        user_scenario=scenario,
        stream_endpoint=(
            str(stream_info.get("producerEndpoint") or "") if use_react_runtime else ""
        ),
        init_stream_endpoint=(
            str(stream_info.get("producerEndpoint") or "")
            if not use_react_runtime
            else ""
        ),
        workflow_path=str(session.get("workflowPath") or ""),
    )
    dependency_error = runtime_dependency_error_from_text(message)
    if dependency_error:
        session_id = str(stream_info.get("sessionId") or "")
        if session_id and state.chat_stream is not None:
            state.chat_stream.delete_session(session_id)
        state.chat_session = {**state.chat_session, **session_base}
        return _chat_snapshot(
            state,
            "error",
            message,
            extra={"runtimeDependencyError": dependency_error},
        )
    if message.startswith("启动失败"):
        session_id = str(stream_info.get("sessionId") or "")
        if session_id and state.chat_stream is not None:
            state.chat_stream.delete_session(session_id)
        raise RuntimeError(message)
    state.chat_session = {
        **state.chat_session,
        **session_base,
        "sessionId": (
            str(stream_info.get("sessionId") or "") if use_react_runtime else ""
        ),
    }
    if (
        use_react_runtime
        and stream_info.get("sessionId")
        and state.chat_stream is not None
    ):
        state.chat_stream.update_session_snapshot(
            str(stream_info["sessionId"]),
            {
                "backgroundPath": _chat_snapshot(state).get("backgroundPath", ""),
                "characterName": first_character,
                "dialogText": "",
                "historyPath": history_path.as_posix(),
                "status": "idle",
                "statusMessage": message,
                "userDisplayName": user_display_name,
                "voiceLanguage": str(state.chat_session.get("voiceLanguage") or "ja"),
            },
        )
        wait_for_chat_runtime_ready(state, stream_info)
    configure_mobile_access(
        state,
        enabled=mobile_access_enabled,
    )
    return _chat_snapshot(
        state,
        "idle",
        "",
        extra={
            "statusMessage": message,
            **({"_chatInitStreamAttached": True} if init_stream_info else {}),
        },
    )

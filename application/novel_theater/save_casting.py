"""Save updated Novel Theater casting bindings with ACK confirmation and prompt refresh."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
import uuid

from ai.llm.template.integrations.localization import resolve_template_locale
from ai.llm.template.session.novel_theater import render_novel_director_prompt
from application.chat.build_effect_context import build_effect_context
from application.chat.conversation_library import (
    _record,
    update_conversation_launch_fields,
)
from application.chat.history.paths import resolve_history_path_for_project
from application.chat.templates import _compose_runtime_template
from application.novel_theater.casting import (
    NOVEL_NAME_MODE_STORY,
    normalize_novel_name_mode,
)
from application.novel_theater.prepare_launch import (
    NOVEL_THEATER_BEHAVIOR_ID,
    build_novel_system_template,
    normalize_cast_bindings,
)
from application.session_behavior.protocol import CommandResolution
from core.chat_history.behavior_state_models import BehaviorVersionConflictError
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import borrow_session_store_for_dir
from core.chat_history.storage import (
    chat_history_session_dir,
    legacy_active_history_branch,
)
from sdk.exception.types import AppError


class _EffectsReader:
    """Narrow effect reader over AppStores or legacy ConfigManager."""

    def __init__(self, state: Any) -> None:
        self._state = state

    def list_effects(self) -> Sequence[Any]:
        stores = getattr(self._state, "stores", None)
        effects_port = getattr(stores, "effects", None)
        list_all = getattr(effects_port, "list_all", None) if effects_port else None
        if callable(list_all):
            return tuple(list_all() or ())
        cfg = getattr(getattr(self._state, "config_manager", None), "config", None)
        return tuple(getattr(cfg, "effect_list", ()) or ())


def build_novel_runtime_system_prompt(
    state: Any,
    launch_fields: Mapping[str, Any],
    *,
    locale: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(director_scenario, system_template, runtime_system_prompt)``."""
    config_manager = getattr(state, "config_manager", None)
    effective_locale = locale or resolve_template_locale(config_manager)
    raw_entries = launch_fields.get("castEntries") or ()
    cast_entries = [dict(item) for item in raw_entries if isinstance(item, Mapping)]
    name_mode = normalize_novel_name_mode(
        launch_fields.get("nameMode"),
        default=NOVEL_NAME_MODE_STORY,
    )
    director_scenario = render_novel_director_prompt(
        cast_entries,
        name_mode=name_mode,
        locale=effective_locale,
    )
    system_template = build_novel_system_template(
        state,
        {**dict(launch_fields), "nameMode": name_mode, "scenario": director_scenario},
    )
    use_effect = bool(launch_fields.get("useEffect", True))
    raw_effects = launch_fields.get("effectNames")
    effect_context = (
        build_effect_context(_EffectsReader(state), raw_effects)
        if use_effect and isinstance(raw_effects, list) and raw_effects
        else None
    )
    runtime_system_prompt = _compose_runtime_template(
        system_template,
        director_scenario,
        effect_context,
        locale=effective_locale,
    )
    return director_scenario, system_template, runtime_system_prompt


def _is_active_session_dir(state: Any, session_dir: Any) -> bool:
    active_history = str(
        (getattr(state, "chat_session", None) or {}).get("historyPath") or ""
    ).strip()
    if not active_history:
        return False
    try:
        active_session_dir = chat_history_session_dir(
            resolve_history_path_for_project(state, active_history)
        ).resolve(strict=False)
    except (OSError, ValueError):
        return False
    return active_session_dir == session_dir.resolve(strict=False)


def _dispatch_live_casting_update(
    state: Any,
    *,
    expected_state_version: int,
    casting_payload: dict[str, Any],
    cast_entries: list[dict[str, Any]],
    runtime_system_prompt: str,
    name_mode: str = NOVEL_NAME_MODE_STORY,
) -> bool:
    """Send live ``update_casting`` command and wait for confirmation; return False only if inactive."""
    from application.chat.composition import _chat_process_running, _handle_chat_command

    command = {
        "type": "behavior-command",
        "cmdId": uuid.uuid4().hex,
        "payload": {
            "commandId": uuid.uuid4().hex,
            "action": "update_casting",
            "expectedStateVersion": expected_state_version,
            "payload": {
                "casting": casting_payload,
                "castEntries": cast_entries,
                "nameMode": name_mode,
                "systemPrompt": runtime_system_prompt,
            },
        },
    }
    chat_stream = getattr(state, "chat_stream", None)
    session_id = str(
        (getattr(state, "chat_session", None) or {}).get("sessionId") or ""
    ).strip()
    wait_ack = getattr(chat_stream, "send_command_and_wait_ack", None)
    if session_id and callable(wait_ack):
        ack = wait_ack(session_id, command, timeout=5.0)
        if ack.get("delivered"):
            if not ack.get("ok"):
                http_status = int(ack.get("httpStatus") or 0)
                if not http_status:
                    http_status = 504 if ack.get("timedOut") else 400
                raise AppError(
                    str(ack.get("errorCode") or "behavior.command.rejected"),
                    fallback_message=str(
                        ack.get("error") or "Casting update rejected by active runtime."
                    ),
                    http_status=http_status,
                )
            return True
        if _chat_process_running():
            raise AppError(
                "behavior.command.rejected",
                fallback_message="Chat runtime stream is not ready to accept casting updates.",
                http_status=503,
            )
        return False

    try:
        res = _handle_chat_command(state, command)
    except RuntimeError as exc:
        if _chat_process_running():
            raise AppError(
                "behavior.command.rejected",
                fallback_message=str(exc) or "Casting update could not be delivered.",
                http_status=503,
            ) from exc
        return False
    if isinstance(res, CommandResolution) and res.status not in {
        "accepted",
        "duplicate",
    }:
        raise AppError(
            res.error_code or "behavior.command.rejected",
            fallback_message=res.error_message or "Casting update rejected.",
            http_status=409 if res.status == "stale_version" else 400,
        )
    return True


def save_novel_casting(
    state: Any,
    conversation_id: str,
    raw_bindings: Sequence[Mapping[str, Any]],
    *,
    name_mode: str | None = None,
) -> dict[str, Any]:
    """Commit updated cast & prompt to live runtime or SQLite first, then update metadata."""
    clean_id = str(conversation_id or "").strip()
    try:
        record = _record(state, clean_id)
    except KeyError as exc:
        raise AppError(
            "novel.conversation_not_found",
            params={"conversationId": clean_id},
            fallback_message="Conversation not found.",
            http_status=404,
        ) from exc

    existing_launch = (
        dict(record.get("launch")) if isinstance(record.get("launch"), Mapping) else {}
    )
    existing_mode = normalize_novel_name_mode(
        existing_launch.get("nameMode"),
        default=NOVEL_NAME_MODE_STORY,
    )
    effective_name_mode = (
        normalize_novel_name_mode(name_mode, default=existing_mode)
        if isinstance(name_mode, str) and name_mode.strip()
        else existing_mode
    )
    casting_map, bound_characters, cast_entries = normalize_cast_bindings(
        raw_bindings,
        getattr(state, "config_manager", None),
        name_mode=effective_name_mode,
    )
    merged_launch = {
        **existing_launch,
        "casting": casting_map.to_dict(),
        "castEntries": cast_entries,
        "characters": bound_characters,
        "nameMode": effective_name_mode,
    }
    director_scenario, system_template, runtime_system_prompt = (
        build_novel_runtime_system_prompt(state, merged_launch)
    )

    history_path = resolve_history_path_for_project(state, record["historyPath"])
    session_dir = chat_history_session_dir(history_path)
    live_committed = False
    if _is_active_session_dir(state, session_dir):
        from application.chat.composition import _chat_snapshot

        snap = _chat_snapshot(state)
        behavior_snap = snap.get("behavior") if isinstance(snap, dict) else None
        if (
            isinstance(behavior_snap, dict)
            and behavior_snap.get("behaviorId") == NOVEL_THEATER_BEHAVIOR_ID
        ):
            live_committed = _dispatch_live_casting_update(
                state,
                expected_state_version=int(behavior_snap.get("stateVersion") or 0),
                casting_payload=casting_map.to_dict(),
                cast_entries=cast_entries,
                runtime_system_prompt=runtime_system_prompt,
                name_mode=effective_name_mode,
            )

    if not live_committed:
        branch_id = legacy_active_history_branch(history_path)
        with borrow_session_store_for_dir(session_dir, create_if_dir_exists=False) as store:
            if store is not None:
                behavior_store = BehaviorStateStore(store, session_dir)
                latest = behavior_store.get_latest_state(branch_id)
                if latest is not None and latest.behavior_id == NOVEL_THEATER_BEHAVIOR_ID:
                    next_state = {
                        **latest.state,
                        "casting": casting_map.to_dict(),
                        "castEntries": cast_entries,
                        "nameMode": effective_name_mode,
                    }
                    try:
                        behavior_store.commit_behavior_turn(
                            branch_id=branch_id,
                            behavior_id=NOVEL_THEATER_BEHAVIOR_ID,
                            expected_state_version=latest.state_version,
                            next_state=next_state,
                            messages=(
                                ({"role": "system", "content": runtime_system_prompt},)
                                if runtime_system_prompt
                                else ()
                            ),
                        )
                    except BehaviorVersionConflictError as exc:
                        raise AppError(
                            "behavior.stale_state_version",
                            fallback_message=str(exc),
                            http_status=409,
                        ) from exc

    return update_conversation_launch_fields(
        state,
        clean_id,
        {
            "casting": casting_map.to_dict(),
            "castEntries": cast_entries,
            "characters": bound_characters,
            "nameMode": effective_name_mode,
            "scenario": director_scenario,
            "system": system_template,
        },
    )


__all__ = [
    "build_novel_runtime_system_prompt",
    "save_novel_casting",
]

"""Compatibility entry points and composition root for chat runtime services."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from core.paths import app_root as runtime_app_root
from core.paths import project_root as runtime_project_root
from core.paths import source_root as runtime_source_root
from core.chat_history.storage import (
    chat_history_active_path,
    load_branch_state,
    save_branch_state,
)  # Compatibility exports used by existing chat integrations.

from application.chat.history_paths import resolve_history_path_for_project
from application.chat.build_effect_context import SelectedEffectContext
from application.chat.mobile_access import (
    get_mobile_access_info,
)
from application.chat.templates import TEMP_SPLIT_META
from application.runtime.dependencies import runtime_dependency_error_from_text
from application.runtime.state import BridgeState
from application.story.coordinator import (
    bound_story_session,
    clear_story_session,
    discard_story_session_storage,
    publish_story_transition,
    story_snapshot_patch,
)
from application.chat.launch_args import CHAT_LAUNCH_CONFIG_ENV

from application.chat import (
    runtime_projection as projection,
    runtime_history as history,
    runtime_story as story,
)
from application.chat.runtime_ports import (
    ProcessSystem,
    HistoryAccess,
    StoryCoordinatorAccess,
)
from application.chat.process_supervisor import (
    ChatProcessSupervisor,
    ProcessTermination,
    tail_text,
)
from application.chat.launch_preparation import ChatLaunchPreparation
from application.chat.runtime_commands import (
    ChatCommandRouter,
    HistoryCommands,
    PluginPresentationCommands,
    TurnOptionsCommands,
    InputCommands,
    SelectionCommands,
    RuntimeControlCommands,
    BranchCommands,
)

TRANSPARENT_BACKGROUND_NAME = projection.TRANSPARENT_BACKGROUND_NAME
_main_chat_process: subprocess.Popen[bytes] | None = None
_main_chat_process_lock = threading.Lock()
_main_chat_log_file: Any = None


def _is_transparent_background_name(name: str | None) -> bool:
    return projection._is_transparent_background_name(name)


def _chat_runtime_mode(_state: BridgeState) -> str:
    return projection._chat_runtime_mode(_state)


def _chat_experimental_features(state: BridgeState) -> dict[str, bool]:
    return projection._chat_experimental_features(state)


def _chat_turn_options(state: BridgeState) -> dict[str, Any]:
    return projection._chat_turn_options(state)


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    return _termination.hidden_kwargs()


def _chat_process_running() -> bool:
    return _supervisor.running()


def _chat_runtime_closing(state: BridgeState) -> bool:
    return projection._chat_runtime_closing(state)


def _chat_runtime_status(state: BridgeState) -> dict[str, Any]:
    running = _chat_process_running()
    closing = _chat_runtime_closing(state)
    runtime_state = "closing" if closing else "running" if running else "idle"
    return {
        "state": runtime_state,
        "chatProcessRunning": running,
        "chatRuntimeClosing": closing,
    }


def _set_chat_runtime_closing(state: BridgeState, closing: bool) -> None:
    return projection._set_chat_runtime_closing(state, closing)


def _chat_log_path() -> Path:
    log_dir = _project_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "main.log"


def _tail_text(path: Path, max_chars: int = 2400) -> str:
    return tail_text(path, max_chars)


def _close_chat_log_if_needed() -> None:
    return _supervisor.close_log()


def _popen_chat_process(
    cmd: list[str], *, cwd: Path, env: dict[str, str]
) -> tuple[subprocess.Popen[bytes], Path]:
    return _supervisor.spawn(cmd, cwd=cwd, env=env)


def _failed_launch_message(exit_code: int, log_path: Path) -> str:
    tail = _tail_text(log_path).strip()
    detail = f"\n\n日志尾部:\n{tail}" if tail else ""
    dependency_error = runtime_dependency_error_from_text(tail, log_path=log_path)
    dependency_hint = ""
    if dependency_error:
        dependency_hint = f"\n缺少 Python 模块: {dependency_error['moduleName']}\n建议安装包: {dependency_error['packageName']}"
    return f"启动失败: 聊天进程已退出，退出码 {exit_code}。\n日志: {log_path}{dependency_hint}{detail}"


def _chat_process_started_message(process: subprocess.Popen[bytes]) -> str:
    return f"聊天进程已启动！PID: {process.pid}"


def _signal_process_tree(process: subprocess.Popen[bytes], signum: int) -> None:
    return _termination.signal_tree(process, signum)


def _wait_process_exit(process: subprocess.Popen[bytes], timeout: float) -> bool:
    return _termination.wait_exit(process, timeout)


def _stop_chat_process(
    process: subprocess.Popen[bytes], *, wait_timeout: float
) -> None:
    return _termination.stop(process, wait_timeout=wait_timeout)


def shutdown_active_chat_process(
    *, wait_timeout: float = 1.2, wait_before_signal: float = 0.0
) -> None:
    return _supervisor.shutdown(
        wait_timeout=wait_timeout, wait_before_signal=wait_before_signal
    )


def _release_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return runtime_source_root()


def _project_root() -> Path:
    return runtime_project_root()


def _source_root() -> Path:
    return runtime_source_root()


def _app_root(state: BridgeState) -> Path:
    for raw in (
        str(getattr(state, "app_root_dir", "") or "").strip(),
        os.environ.get("SHINSEKAI_APP_ROOT", "").strip(),
    ):
        if not raw:
            continue
        path = Path(raw).expanduser().resolve(strict=False)
        if path.exists() and path.is_dir():
            return path
    return runtime_app_root()


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve(strict=False)
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _main_exe_candidates(state: BridgeState) -> list[Path]:
    roots = _unique_paths([_app_root(state), _source_root()])
    return _unique_paths(
        [
            candidate
            for root in roots
            for candidate in (root / "main" / "main.exe", root / "main.exe")
        ]
    )


def _main_py_path() -> Path:
    return _source_root() / "main.py"


def _launch_chat(
    state: BridgeState,
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
) -> str:
    return _supervisor.launch(
        lambda: _launch_preparation.prepare(
            state,
            character_names=character_names,
            effect_names=effect_names,
            effect_context=effect_context,
            history_file=history_file,
            init_sprite_path=init_sprite_path,
            show_initial_sprite=show_initial_sprite,
            room_id=room_id,
            selected_bg=selected_bg,
            system_template=system_template,
            use_cg=use_cg,
            user_scenario=user_scenario,
            stream_endpoint=stream_endpoint,
            init_stream_endpoint=init_stream_endpoint,
            workflow_path=workflow_path,
            media_selection_mode=media_selection_mode,
            use_current_template_for_history=use_current_template_for_history,
        ),
        session_id=str(
            (getattr(state, "chat_session", {}) or {}).get("sessionId") or ""
        ).strip(),
    )


def _resolve_history_file(state: BridgeState, raw_path: str | Path) -> Path:
    return resolve_history_path_for_project(state, raw_path)


def _sprite_path(sprite: Any) -> str:
    return projection._sprite_path(sprite)


def _chat_session_media(state: BridgeState) -> tuple[str, str, list[dict[str, Any]]]:
    return projection._chat_session_media(state)


def _chat_voice_language(state: BridgeState) -> str:
    return projection._chat_voice_language(state)


def _sanitize_user_display_name(value: Any) -> str:
    return projection._sanitize_user_display_name(value)


def _chat_user_display_name(state: BridgeState) -> str:
    return projection._chat_user_display_name(state)


def _chat_user_display_name_from_snapshot(
    state: BridgeState, snapshot: dict[str, Any] | None = None
) -> str:
    return projection._chat_user_display_name_from_snapshot(state, snapshot)


def _history_entry_role_from_text(text: str) -> str:
    return history._history_entry_role_from_text(text)


def _message_created_at_ms(message: dict[str, Any]) -> int | None:
    return history._message_created_at_ms(message)


def _serialize_history_entries_from_messages(
    messages: Any, user_display_name: str = history._DEFAULT_USER_DISPLAY_NAME
) -> list[dict[str, Any]]:
    return history._serialize_history_entries_from_messages(messages, user_display_name)


def _history_entries_from_snapshot(
    snapshot: dict[str, Any] | None
) -> list[dict[str, Any]]:
    return history._history_entries_from_snapshot(snapshot)


def _chat_history_entries(state: BridgeState) -> list[dict[str, Any]]:
    return _history_projection.entries(state)


def _chat_history(state: BridgeState) -> list[dict[str, Any]]:
    return _chat_history_entries(state)


def _chat_snapshot(
    state: BridgeState,
    status: str | None = None,
    message: str = "",
    *,
    extra: dict[str, Any] | None = None,
    renderer_id: str = "",
) -> dict[str, Any]:
    return _snapshot_projection.build(
        state, status, message, extra=extra, renderer_id=renderer_id
    )


def _chat_stream_initial_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return projection._chat_stream_initial_snapshot(snapshot)


def _plain_history_text(raw: Any) -> str:
    return history._plain_history_text(raw)


def _plain_history_text_from_entries(entries: list[dict[str, Any]]) -> str:
    return history._plain_history_text_from_entries(entries)


def _read_history_file(path: Path) -> Any:
    return history._read_history_file(path)


def _current_chat_history_download_file(state: BridgeState) -> Path:
    return _history_downloads.current_file(state)


def _history_download_state(
    state: BridgeState,
) -> tuple[threading.Lock, dict[str, tuple[str, float]]]:
    return history._history_download_state(state)


def _issue_chat_history_download_capability(
    state: BridgeState, history_file: Path
) -> str:
    return _history_downloads.issue(state, history_file)


def _chat_history_download_file(state: BridgeState, capability: str) -> Path:
    return _history_downloads.fetch(state, capability)


def _story_choice_label(session: Any, choice_id: str) -> str:
    return story._story_choice_label(session, choice_id)


def _persist_story_choice_messages(
    state: BridgeState, label: str, user_name: str
) -> None:
    return _story_history.persist_choice(state, label, user_name)


def _record_story_choice_history(
    state: BridgeState, label: str
) -> list[dict[str, Any]]:
    return _story_history.record_choice(state, label)


def _scene_history_role(character_id: str) -> str:
    return story._scene_history_role(character_id)


def _scene_turn_already_recorded(
    entries: Sequence[dict[str, Any]], user_text: str, dialogue: Sequence[Any]
) -> bool:
    return story._scene_turn_already_recorded(entries, user_text, dialogue)


def _persist_scene_turn_messages(
    state: BridgeState, user_text: str, user_name: str, dialogue: Sequence[Any]
) -> None:
    return _story_history.persist_scene(state, user_text, user_name, dialogue)


def _record_scene_turn_history(
    state: BridgeState, user_text: str, dialogue: Sequence[Any]
) -> list[dict[str, Any]]:
    return _story_history.record_scene(state, user_text, dialogue)


def _scene_dialog_events(dialogue: Sequence[Any]) -> list[dict[str, Any]]:
    return story._scene_dialog_events(dialogue)


def _allocate_aligned_story_branch_id(state: BridgeState, session: Any) -> str:
    return _story_branches.allocate_id(state, session)


def _sync_story_session_branch_command(
    state: BridgeState, command: str, body: dict[str, Any]
) -> None:
    return _story_branches.sync(state, command, body)


def _publish_bound_story_transition(state: BridgeState) -> None:
    return _story_branches.publish(state)


def _discard_bound_story_session(state: BridgeState) -> None:
    return _story_branches.discard(state)


def _handle_chat_command(state: BridgeState, body: dict[str, Any]) -> dict[str, Any]:
    return _command_router.handle(state, body)


def _chat_theme_payload(state: BridgeState) -> dict[str, Any]:
    return projection._chat_theme_payload(state)


class _LegacyProcessResources:
    """Adapt the historical process slots without duplicating mutable ownership."""

    @property
    def process(self):
        return _main_chat_process

    @process.setter
    def process(self, value):
        global _main_chat_process
        _main_chat_process = value

    @property
    def log(self):
        return _main_chat_log_file

    @log.setter
    def log(self, value):
        global _main_chat_log_file
        _main_chat_log_file = value

    @property
    def lock(self):
        return _main_chat_process_lock


def _publish_process_lifecycle(context):
    from plugin_system.host.service import get_plugin_hook_dispatcher

    dispatcher = get_plugin_hook_dispatcher()
    if dispatcher is not None:
        dispatcher.dispatch_chat_process(context)


_process_system = ProcessSystem(
    platform=lambda: os.name,
    monotonic=lambda: time.monotonic(),
    group_signal=lambda pid, signum: os.killpg(pid, signum),
    popen=lambda command, **kwargs: subprocess.Popen(command, **kwargs),
)
_termination = ProcessTermination(_process_system)
_supervisor = ChatProcessSupervisor(
    system=_process_system,
    log_path=lambda: _chat_log_path(),
    hidden_kwargs=lambda: _hidden_subprocess_kwargs(),
    stop_child=lambda child, **kwargs: _stop_chat_process(child, **kwargs),
    wait_exit=lambda child, timeout: _wait_process_exit(child, timeout),
    monotonic=lambda: time.monotonic(),
    failed_launch=lambda code, path: _failed_launch_message(code, path),
    resources=_LegacyProcessResources(),
    publish=lambda context: _publish_process_lifecycle(context),
    spawn=lambda command, **kwargs: _popen_chat_process(command, **kwargs),
)
_launch_preparation = ChatLaunchPreparation(
    project_root=lambda: _project_root(),
    app_root=lambda state: _app_root(state),
    exe_candidates=lambda state: _main_exe_candidates(state),
    main_py=lambda: _main_py_path(),
)
_history_access = HistoryAccess(
    entries=lambda state: _chat_history_entries(state),
    resolve=lambda state, path: _resolve_history_file(state, path),
    read=lambda path: _read_history_file(path),
)
_history_projection = history.HistoryProjection(
    resolve=_history_access.resolve,
    read=_history_access.read,
    user_name=lambda state: _chat_user_display_name(state),
)
_history_downloads = history.HistoryDownloads(
    resolve=_history_access.resolve,
    clock=lambda: time.monotonic(),
    token=lambda: uuid.uuid4().hex,
)
_story_access = StoryCoordinatorAccess(
    session=lambda state: bound_story_session(state),
    patch=lambda state: story_snapshot_patch(state),
    publish=lambda state, patch, **kwargs: publish_story_transition(
        state, patch, **kwargs
    ),
    clear=lambda state: clear_story_session(state),
    discard=lambda path: discard_story_session_storage(path),
)
_story_history = story.StoryHistoryRecorder(
    _history_access, lambda state: _chat_user_display_name_from_snapshot(state)
)
_story_branches = story.StoryBranchCoordinator(_story_access, _history_access.resolve)
_snapshot_projection = projection.SnapshotProjection(
    history=_history_access.entries,
    running=lambda: _chat_process_running(),
    story_patch=_story_access.patch,
    mobile_info=lambda state: get_mobile_access_info(state),
)
_command_router = ChatCommandRouter(
    lambda state, *args, **kwargs: _chat_snapshot(state, *args, **kwargs)
)
_history_commands = HistoryCommands(
    history=_history_access,
    download_file=lambda state: _current_chat_history_download_file(state),
    issue_download=lambda state, path: _issue_chat_history_download_capability(
        state, path
    ),
    discard_story=lambda state: _discard_bound_story_session(state),
)
_input_commands = InputCommands(
    turn_options=lambda state: _chat_turn_options(state),
    user_name=lambda state: _chat_user_display_name_from_snapshot(state),
)
_selection_commands = SelectionCommands(
    story=_story_access,
    record_choice=lambda state, label: _record_story_choice_history(state, label),
    choice_label=lambda session, choice: _story_choice_label(session, choice),
    text_selection=_input_commands.message,
)
_turn_commands = TurnOptionsCommands(lambda state: _chat_turn_options(state))
_plugin_commands = PluginPresentationCommands()
_control_commands = RuntimeControlCommands()
_branch_commands = BranchCommands(
    features=lambda state: _chat_experimental_features(state),
    sync=lambda state, command, body: _sync_story_session_branch_command(
        state, command, body
    ),
    publish=lambda state: _publish_bound_story_transition(state),
)

_command_router.register("copy-history", _history_commands.copy_history, runtime=False)
_command_router.register("open-history", _history_commands.open_history, runtime=False)
_command_router.register("clear-history", _history_commands.clear_history, runtime=True)
_command_router.register("dismiss-plugin-page", _plugin_commands.dismiss, runtime=False)
_command_router.register("update-turn-options", _turn_commands.update, runtime=True)
_command_router.register("send-message", _input_commands.message, runtime=True)
_command_router.register("submit-option", _selection_commands.submit, runtime=True)
_command_router.register(
    "chat-input-state", _control_commands.input_batch, runtime=True
)
_command_router.register(
    "flush-input-batch", _control_commands.input_batch, runtime=True
)
_command_router.register(
    "cancel-input-batch", _control_commands.input_batch, runtime=True
)
_command_router.register(
    "audio-playback-signal", _control_commands.audio_playback, runtime=True
)
_command_router.register("skip-speech", _control_commands.skip_speech, runtime=True)
_command_router.register("dialog-advance", _control_commands.advance, runtime=True)
_command_router.register(
    "change-voice-language", _control_commands.voice_language, runtime=True
)
_command_router.register("pause-asr", _control_commands.pause_asr, runtime=True)
_command_router.register("resume-asr", _control_commands.resume_asr, runtime=True)
_command_router.register("begin-asr-hold", _control_commands.asr_hold, runtime=True)
_command_router.register("finish-asr-hold", _control_commands.asr_hold, runtime=True)
_command_router.register("cancel-asr-hold", _control_commands.asr_hold, runtime=True)
_command_router.register("reroll", _control_commands.reroll, runtime=True)
_command_router.register("revert-history", _branch_commands.revert, runtime=True)
_command_router.register("fork-history", _branch_commands.fork, runtime=True)
_command_router.register("switch-branch", _branch_commands.switch, runtime=True)
_command_router.register("rename-branch", _branch_commands.rename, runtime=True)

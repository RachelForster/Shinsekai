"""Default service composition and application entry points for chat."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from core.paths import app_root as runtime_app_root
from core.paths import project_root as runtime_project_root
from core.paths import source_root as runtime_source_root

from application.chat.history_paths import resolve_history_path_for_project
from application.chat.build_effect_context import SelectedEffectContext
from application.chat.mobile_access import (
    get_mobile_access_info,
)
from application.runtime.dependencies import runtime_dependency_error_from_text
from application.runtime.state import BridgeState
from application.story.coordinator import (
    bound_story_session,
    clear_story_session,
    discard_story_session_storage,
    publish_story_transition,
    story_snapshot_patch,
)

from application.chat import (
    runtime_projection as projection,
    runtime_history as history,
    runtime_story as story,
)
from application.chat.runtime_ports import (
    ProcessSystem,
    StoryCoordinatorAccess,
)
from application.chat.process_supervisor import (
    ChatProcessSupervisor,
    ProcessTermination,
    tail_text,
)
from application.chat.launch_preparation import ChatLaunchPreparation
from application.chat.events import LifecycleEvents
from application.chat.lifecycle_diagnostics import LifecycleDiagnostics
from application.chat.session_lifecycle import ChatSessionLifecycle, SessionEffects
from application.chat.mobile_access import configure_mobile_access, stop_mobile_access
from application.chat.launch_history import persist_confirmed_history_path
from sdk.chat_process import ChatProcessContext
from sdk.chat_session import ChatSessionContext
from application.chat.runtime_commands import (
    ChatCommandRouter,
    dismiss_plugin_page,
    input_batch,
    audio_playback,
    skip_speech,
    advance,
    voice_language,
    pause_asr,
    resume_asr,
    asr_hold,
    reroll,
    HistoryCommands,
    TurnOptionsCommands,
    InputCommands,
    SelectionCommands,
    BranchCommands,
)


def _chat_runtime_status(state: BridgeState) -> dict[str, Any]:
    running = _supervisor.running()
    closing = projection._chat_runtime_closing(state)
    runtime_state = "closing" if closing else "running" if running else "idle"
    return {
        "state": runtime_state,
        "chatProcessRunning": running,
        "chatRuntimeClosing": closing,
    }


def _chat_log_path() -> Path:
    log_dir = runtime_project_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "main.log"


def _failed_launch_message(exit_code: int, log_path: Path) -> str:
    tail = tail_text(log_path).strip()
    detail = f"\n\n日志尾部:\n{tail}" if tail else ""
    dependency_error = runtime_dependency_error_from_text(tail, log_path=log_path)
    dependency_hint = ""
    if dependency_error:
        dependency_hint = f"\n缺少 Python 模块: {dependency_error['moduleName']}\n建议安装包: {dependency_error['packageName']}"
    return f"启动失败: 聊天进程已退出，退出码 {exit_code}。\n日志: {log_path}{dependency_hint}{detail}"


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
    roots = _unique_paths([_app_root(state), runtime_source_root()])
    return _unique_paths(
        [
            candidate
            for root in roots
            for candidate in (root / "main" / "main.exe", root / "main.exe")
        ]
    )


def _main_py_path() -> Path:
    return runtime_source_root() / "main.py"


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
    session_id: str | None = None,
    launch_id: str = "",
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
        session_id=(
            str(session_id).strip()
            if session_id is not None
            else str(
                (getattr(state, "chat_session", {}) or {}).get("sessionId") or ""
            ).strip()
        ),
        launch_id=launch_id,
    )


def _publish_process_lifecycle(context):
    from plugin_system.host.service import get_plugin_hook_dispatcher

    dispatcher = get_plugin_hook_dispatcher()
    if dispatcher is not None:
        if isinstance(context, ChatProcessContext):
            dispatcher.dispatch_chat_process(context)
        elif isinstance(context, ChatSessionContext):
            dispatcher.dispatch_chat_session(context)


def _session_lifecycle(state, **effects) -> ChatSessionLifecycle:
    service = getattr(state, "chat_session_lifecycle", None)
    if service is None:
        service = ChatSessionLifecycle(
            state,
            _application_events,
            SessionEffects(
                configure_mobile=configure_mobile_access,
                stop_mobile=stop_mobile_access,
                remember_history=persist_confirmed_history_path,
                clear_story=clear_story_session,
            ),
        )
        state.chat_session_lifecycle = service
    for name, callback in effects.items():
        setattr(service.effects, name, callback)
    return service


_application_events = LifecycleEvents()
_application_events.subscribe(LifecycleDiagnostics())
_application_events.subscribe(_publish_process_lifecycle)


_process_system = ProcessSystem(
    platform=lambda: os.name,
    monotonic=time.monotonic,
    group_signal=lambda pid, signum: os.killpg(pid, signum),
    popen=lambda command, **kwargs: subprocess.Popen(command, **kwargs),
)
_termination = ProcessTermination(_process_system)
_supervisor = ChatProcessSupervisor(
    system=_process_system,
    log_path=_chat_log_path,
    hidden_kwargs=_termination.hidden_kwargs,
    stop_child=_termination.stop,
    wait_exit=_termination.wait_exit,
    monotonic=time.monotonic,
    failed_launch=_failed_launch_message,
    handle_event=_application_events.emit,
    watch_exits=True,
)
_launch_preparation = ChatLaunchPreparation(
    project_root=runtime_project_root,
    app_root=_app_root,
    exe_candidates=_main_exe_candidates,
    main_py=_main_py_path,
)
_history_projection = history.HistoryProjection(
    resolve=resolve_history_path_for_project,
    read=history._read_history_file,
    user_name=projection._chat_user_display_name,
)
_history_downloads = history.HistoryDownloads(
    resolve=resolve_history_path_for_project,
    clock=time.monotonic,
    token=lambda: uuid.uuid4().hex,
)
_story_access = StoryCoordinatorAccess(
    session=bound_story_session,
    patch=story_snapshot_patch,
    publish=publish_story_transition,
    clear=clear_story_session,
    discard=discard_story_session_storage,
)
_story_history = story.StoryHistoryRecorder(
    _history_projection, projection._chat_user_display_name_from_snapshot
)
_story_branches = story.StoryBranchCoordinator(
    _story_access, resolve_history_path_for_project
)
_snapshot_projection = projection.SnapshotProjection(
    history=_history_projection.entries,
    running=_supervisor.running,
    story_patch=story_snapshot_patch,
    mobile_info=get_mobile_access_info,
)
_command_router = ChatCommandRouter(_snapshot_projection.build)
_history_commands = HistoryCommands(
    history=_history_projection,
    download_file=_history_downloads.current_file,
    issue_download=_history_downloads.issue,
    discard_story=_story_branches.discard,
)
_input_commands = InputCommands(
    turn_options=projection._chat_turn_options,
    user_name=projection._chat_user_display_name_from_snapshot,
)
_selection_commands = SelectionCommands(
    story=_story_access,
    record_choice=_story_history.record_choice,
    choice_label=story._story_choice_label,
    text_selection=_input_commands.message,
)
_turn_commands = TurnOptionsCommands(projection._chat_turn_options)
_branch_commands = BranchCommands(
    features=projection._chat_experimental_features,
    sync=_story_branches.sync,
    publish=_story_branches.publish,
)

for command, handler in {
    "copy-history": _history_commands.copy_history,
    "open-history": _history_commands.open_history,
    "dismiss-plugin-page": dismiss_plugin_page,
}.items():
    _command_router.register(command, handler, runtime=False)

for command, handler in {
    "clear-history": _history_commands.clear_history,
    "update-turn-options": _turn_commands.update,
    "send-message": _input_commands.message,
    "submit-option": _selection_commands.submit,
    "chat-input-state": input_batch,
    "flush-input-batch": input_batch,
    "cancel-input-batch": input_batch,
    "audio-playback-signal": audio_playback,
    "skip-speech": skip_speech,
    "dialog-advance": advance,
    "change-voice-language": voice_language,
    "pause-asr": pause_asr,
    "resume-asr": resume_asr,
    "begin-asr-hold": asr_hold,
    "finish-asr-hold": asr_hold,
    "cancel-asr-hold": asr_hold,
    "reroll": reroll,
    "revert-history": _branch_commands.revert,
    "fork-history": _branch_commands.fork,
    "switch-branch": _branch_commands.switch,
    "rename-branch": _branch_commands.rename,
}.items():
    _command_router.register(command, handler)

# Application entry points use the owned services directly.
_chat_process_running = _supervisor.running
shutdown_active_chat_process = _supervisor.shutdown
_chat_snapshot = _snapshot_projection.build
_chat_history = _history_projection.entries
_chat_history_download_file = _history_downloads.fetch
_handle_chat_command = _command_router.handle

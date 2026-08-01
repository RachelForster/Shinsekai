from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sdk.file_transactions import (
    capture_directory_identity,
    open_binary_read_without_links,
    open_text_append_without_links,
    read_text_without_links,
    require_directory_identity,
)
from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    is_option_history_name,
    normalize_character_name,
)
from sdk.path_contract import app_root as runtime_app_root
from sdk.path_contract import (
    managed_child_path,
    managed_project_storage,
    require_directory_without_links,
    require_regular_file_without_links,
    resolve_executable_file,
    resolve_runtime_asset_read_path,
)
from sdk.path_contract import project_root as runtime_project_root
from sdk.path_contract import source_root as runtime_source_root
from sdk.process_launch import isolated_python_environment
from application.runtime.restart_debug import write_restart_debug_log
from core.media.chat_attachments import (
    CHAT_ATTACHMENT_STAGE_SUBDIR,
    CHAT_ATTACHMENTS_ROOT_ENV,
    chat_attachment_display_text,
    resolve_chat_attachments,
)
from core.sprite.chat_branch_storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
    chat_history_active_path,
    chat_history_download_path,
    chat_history_session_dir,
    remove_chat_history_storage,
)
from core.sprite.chat_history_text import history_payload_to_plain_text, parse_assistant_dialog_content
from core.sprite.sprite_cli import CHAT_LAUNCH_CONFIG_ENV
from ai.tools.chat_ui_tools import sanitize_user_display_name

from .history_paths import (
    history_root_for_state,
    is_unc_history_path,
    prepare_history_reference_for_launch,
    resolve_history_path_for_project,
)
from application.chat.mobile_access import (
    get_mobile_access_info,
    stop_mobile_access,
)
from sdk.path_references import (
    resolve_from_root,
    resolved_path_is_within,
    state_project_root,
)
from application.runtime.dependencies import runtime_dependency_error_from_text
from sdk.path_references import portable_path_text
from sdk.path_utils import reject_control_chars, safe_child_path
from application.runtime.state import BridgeState
from .templates import (
    TEMP_SPLIT_META,
    _compose_runtime_template,
    _effective_user_scenario,
    _history_id_from_scenario,
    _scenario_from_template_like,
    _template_dir,
    _write_runtime_template_files,
)

TRANSPARENT_BACKGROUND_NAME = "透明场景"
_TRANSPARENT_BACKGROUND_ALIAS = "透明背景"
_HISTORY_DOWNLOAD_CAPABILITY_TTL_SECONDS = 60.0
_RUNTIME_CHAT_COMMANDS = {
    "audio-playback-signal",
    "cancel-input-batch",
    "change-voice-language",
    "chat-input-state",
    "clear-history",
    "dialog-advance",
    "flush-input-batch",
    "fork-history",
    "pause-asr",
    "rename-branch",
    "resume-asr",
    "reroll",
    "revert-history",
    "send-message",
    "skip-speech",
    "switch-branch",
    "submit-option",
    "update-turn-options",
}
_main_chat_process: subprocess.Popen[bytes] | None = None
_main_chat_process_lock = threading.Lock()
_main_chat_log_file: Any = None
_chat_transition_lock_creation = threading.Lock()
_SYSTEM_HISTORY_NAMES = COT_ALIASES | NARR_ALIASES | STAT_ALIASES | SCENE_ALIASES | BGM_ALIASES | CG_ALIASES
_DEFAULT_USER_DISPLAY_NAME = "你"


def _chat_debug_log(message: str) -> None:
    write_restart_debug_log("chat_launch", message)


def _is_transparent_background_name(name: str | None) -> bool:
    value = str(name or "").strip()
    return not value or value in {TRANSPARENT_BACKGROUND_NAME, _TRANSPARENT_BACKGROUND_ALIAS}


def _chat_runtime_mode(_state: BridgeState) -> str:
    """Return the only supported chat UI runtime."""
    return "react"


def _chat_experimental_features(state: BridgeState) -> dict[str, bool]:
    config_manager = getattr(state, "config_manager", None)
    system_config = getattr(getattr(config_manager, "config", None), "system_config", None)
    return {
        "conversationTree": bool(getattr(system_config, "react_chat_flowchart_experimental_enabled", False)),
        "forkHistory": bool(getattr(system_config, "react_chat_fork_experimental_enabled", False)),
    }


def _chat_turn_options(state: BridgeState) -> dict[str, Any]:
    config_manager = getattr(state, "config_manager", None)
    api_config = getattr(getattr(config_manager, "config", None), "api_config", None)
    return {
        "interruptEnabled": bool(getattr(api_config, "interrupt_enabled", True)),
        "batchEnabled": bool(getattr(api_config, "is_batch_input_enabled", False)),
        "batchIdleSeconds": float(getattr(api_config, "batch_input_timeout", 5.0) or 5.0),
    }


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        _chat_debug_log("subprocess_kwargs platform=posix start_new_session=true")
        return {"start_new_session": True}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(
        subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        0x00000200,
    )
    _chat_debug_log(f"subprocess_kwargs platform=windows creationflags={flags}")
    return {"creationflags": flags}


def _chat_process_running() -> bool:
    with _main_chat_process_lock:
        return _main_chat_process is not None and _main_chat_process.poll() is None


def _chat_transition_lock(state: BridgeState) -> threading.RLock:
    """Serialize launch, resume, and close as one state/storage transition."""

    lock = getattr(state, "chat_transition_lock", None)
    if lock is not None:
        return lock
    # SimpleNamespace-based integrations predate the BridgeState field.  Make
    # lazy initialization race-free so they receive the same invariant.
    with _chat_transition_lock_creation:
        lock = getattr(state, "chat_transition_lock", None)
        if lock is None:
            lock = threading.RLock()
            state.chat_transition_lock = lock
    return lock


def _process_return_code(process: subprocess.Popen[bytes]) -> int | None:
    return_code = getattr(process, "returncode", None)
    if return_code is not None:
        return return_code
    return process.poll()


def _chat_runtime_closing(state: BridgeState) -> bool:
    lock = getattr(state, "chat_runtime_lock", None)
    if lock is None:
        return bool(getattr(state, "chat_runtime_closing", False))
    with lock:
        return bool(getattr(state, "chat_runtime_closing", False))


def _chat_runtime_status(state: BridgeState) -> dict[str, Any]:
    running = _chat_process_running()
    # Read closing after the process state. If shutdown starts between the two
    # reads and the process exits quickly, prefer the newer closing signal over
    # an incorrect idle result that would re-enable launch controls too early.
    closing = _chat_runtime_closing(state)
    runtime_state = "closing" if closing else "running" if running else "idle"
    return {
        "state": runtime_state,
        "chatProcessRunning": running,
        "chatRuntimeClosing": closing,
    }


def _set_chat_runtime_closing(state: BridgeState, closing: bool) -> None:
    lock = getattr(state, "chat_runtime_lock", None)
    if lock is None:
        state.chat_runtime_closing = closing
        return
    with lock:
        state.chat_runtime_closing = closing


def _chat_log_path(project_root: Path | None = None) -> Path:
    root = _project_root() if project_root is None else project_root
    log_dir = managed_project_storage("logs", root=root)
    log_dir.mkdir(parents=True, exist_ok=True)
    return managed_child_path(log_dir, "main.log", field="chat log filename")


def _tail_text(path: Path, max_chars: int = 2400) -> str:
    try:
        text = read_text_without_links(path, errors="replace")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _close_chat_log_if_needed() -> None:
    global _main_chat_log_file
    if _main_chat_log_file is None:
        return
    try:
        _main_chat_log_file.close()
    except OSError:
        pass
    _main_chat_log_file = None


def _safe_chat_command(cmd: list[str]) -> list[str]:
    return [portable_path_text(item, field="command argument") for item in cmd]


def _require_launch_file_snapshot(
    path: Path,
    identity: os.stat_result,
) -> None:
    with open_binary_read_without_links(
        path,
        expected_identity=identity,
    ):
        pass


def _terminate_invalid_launch(process: subprocess.Popen[bytes]) -> None:
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _popen_chat_process(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    required_files: tuple[tuple[Path, os.stat_result], ...] = (),
    required_directories: tuple[tuple[Path, os.stat_result], ...] = (),
) -> tuple[subprocess.Popen[bytes], Path]:
    global _main_chat_log_file
    _close_chat_log_if_needed()
    safe_cmd = _safe_chat_command(cmd)
    cwd, cwd_identity = capture_directory_identity(
        cwd,
        field="chat launch working directory",
    )
    for path, identity in required_directories:
        require_directory_identity(
            path,
            identity,
            field="chat launch directory",
        )
    for path, identity in required_files:
        _require_launch_file_snapshot(path, identity)
    log_path = _chat_log_path(cwd)
    log_directory, log_directory_identity = capture_directory_identity(
        log_path.parent,
        field="chat log directory",
    )
    require_directory_identity(
        cwd,
        cwd_identity,
        field="chat launch working directory",
    )
    for path, identity in required_directories:
        require_directory_identity(
            path,
            identity,
            field="chat launch directory",
        )
    for path, identity in required_files:
        _require_launch_file_snapshot(path, identity)
    _main_chat_log_file = open_text_append_without_links(
        log_path,
        expected_parent_identity=log_directory_identity,
    )
    _main_chat_log_file.write(
        "\n"
        + "=" * 60
        + f"\n{datetime.now().isoformat(sep=' ', timespec='seconds')}  main.py launch\n"
        + f"cwd: {cwd}\n"
        + f"cmd: {' '.join(safe_cmd)}\n"
    )
    env = isolated_python_environment(env)
    env["PYTHONUNBUFFERED"] = "1"
    _chat_debug_log(
        f"subprocess_launch cwd={cwd} executable={safe_cmd[0] if safe_cmd else ''} args_count={max(len(safe_cmd) - 1, 0)} log_path={log_path}"
    )
    require_directory_identity(
        cwd,
        cwd_identity,
        field="chat launch working directory",
    )
    for path, identity in required_directories:
        require_directory_identity(
            path,
            identity,
            field="chat launch directory",
        )
    require_directory_identity(
        log_directory,
        log_directory_identity,
        field="chat log directory",
    )
    for path, identity in required_files:
        _require_launch_file_snapshot(path, identity)
    # safe_cmd is an argv list whose entries have passed control-character validation; shell=False is the default.
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    try:
        process = subprocess.Popen(
            safe_cmd,
            cwd=str(cwd),
            env=env,
            stdout=_main_chat_log_file,
            stderr=subprocess.STDOUT,
            **_hidden_subprocess_kwargs(),
        )
    except BaseException:
        _close_chat_log_if_needed()
        raise
    try:
        require_directory_identity(
            cwd,
            cwd_identity,
            field="chat launch working directory",
        )
        for path, identity in required_directories:
            require_directory_identity(
                path,
                identity,
                field="chat launch directory",
            )
        require_directory_identity(
            log_directory,
            log_directory_identity,
            field="chat log directory",
        )
        for path, identity in required_files:
            _require_launch_file_snapshot(path, identity)
    except BaseException:
        _terminate_invalid_launch(process)
        _close_chat_log_if_needed()
        raise
    _chat_debug_log(f"subprocess_started pid={process.pid} log_path={log_path}")
    return process, log_path


def _failed_launch_message(exit_code: int, log_path: Path) -> str:
    tail = _tail_text(log_path).strip()
    detail = f"\n\n日志尾部:\n{tail}" if tail else ""
    dependency_error = runtime_dependency_error_from_text(tail, log_path=log_path)
    dependency_hint = ""
    if dependency_error:
        dependency_hint = (
            f"\n缺少 Python 模块: {dependency_error['moduleName']}"
            f"\n建议安装包: {dependency_error['packageName']}"
        )
    return f"启动失败: 聊天进程已退出，退出码 {exit_code}。\n日志: {log_path}{dependency_hint}{detail}"


def _chat_process_started_message(process: subprocess.Popen[bytes]) -> str:
    return f"聊天进程已启动！PID: {process.pid}"


def _signal_process_tree(process: subprocess.Popen[bytes], signum: int) -> None:
    if os.name != "nt":
        try:
            os.killpg(process.pid, signum)
            return
        except ProcessLookupError:
            if process.poll() is not None:
                return
        except OSError:
            pass
    try:
        process.send_signal(signum)
    except (OSError, ValueError):
        pass


def _wait_process_exit(process: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        process.wait(timeout=max(timeout, 0.0))
        return True
    except subprocess.TimeoutExpired:
        return False


def _stop_chat_process(process: subprocess.Popen[bytes], *, wait_timeout: float) -> None:
    if process.poll() is not None:
        _chat_debug_log(
            f"stop_process skipped pid={process.pid} reason=already_exited code={_process_return_code(process)}"
        )
        return

    _chat_debug_log(f"stop_process start pid={process.pid} wait_timeout={wait_timeout}")
    deadline = time.monotonic() + max(wait_timeout, 0.15)
    graceful_timeout = max(0.45, wait_timeout - 0.7)
    steps: list[tuple[int | str, float]] = [
        (signal.SIGINT, graceful_timeout),
        (signal.SIGTERM, 0.35),
        ("kill", 0.35),
    ]
    for action, step_timeout in steps:
        if process.poll() is not None:
            return
        if action == "kill":
            if os.name != "nt":
                _signal_process_tree(process, signal.SIGKILL)
            else:
                try:
                    process.kill()
                except OSError:
                    pass
        else:
            if os.name == "nt" and action == signal.SIGTERM:
                try:
                    process.terminate()
                except OSError:
                    pass
            else:
                _signal_process_tree(process, int(action))
        remaining = max(0.05, min(step_timeout, deadline - time.monotonic()))
        if _wait_process_exit(process, remaining):
            _chat_debug_log(
                f"stop_process completed pid={process.pid} action={action} code={_process_return_code(process)}"
            )
            return
    _chat_debug_log(f"stop_process timeout pid={process.pid} code={process.poll()}")


def shutdown_active_chat_process(*, wait_timeout: float = 1.2, wait_before_signal: float = 0.0) -> None:
    """Stop the active chat child without needing bridge request state.

    The bridge may be asked to exit from watchdog/signal paths where there is no
    HTTP request object available. Keep this process cleanup independent from
    stream/session bookkeeping so the TTS/audio child cannot outlive the bridge.
    """

    global _main_chat_process

    process: subprocess.Popen[bytes] | None = None
    with _main_chat_process_lock:
        if _main_chat_process is not None and _main_chat_process.poll() is not None:
            _close_chat_log_if_needed()
            _main_chat_process = None
            return
        process = _main_chat_process

    if process is not None and process.poll() is None:
        try:
            started = time.monotonic()
            exited_gracefully = wait_before_signal > 0 and _wait_process_exit(
                process,
                min(wait_before_signal, wait_timeout),
            )
            if not exited_gracefully:
                remaining = max(0.15, wait_timeout - (time.monotonic() - started))
                _stop_chat_process(process, wait_timeout=remaining)
        finally:
            with _main_chat_process_lock:
                if _main_chat_process is process:
                    _main_chat_process = None
                _close_chat_log_if_needed()


def _release_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return runtime_source_root()


def _project_root() -> Path:
    return runtime_project_root()


def _source_root() -> Path:
    return runtime_source_root()


def _app_root(state: BridgeState) -> Path:
    source = "state.app_root_dir"
    raw = str(getattr(state, "app_root_dir", "") or "")
    if raw:
        validated = reject_control_chars(raw, field="app root")
        if validated != raw:
            raise ValueError(f"invalid app root from {source}: non-portable characters")
        try:
            path = require_directory_without_links(
                raw,
                field="chat application root",
            )
        except (NotADirectoryError, ValueError) as exc:
            raise ValueError(f"invalid app root from {source}: must be absolute") from exc
        return path
    return runtime_app_root()


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _main_exe_candidates(state: BridgeState) -> list[Path]:
    roots = _unique_paths([_app_root(state), _source_root()])
    return _unique_paths(
        [candidate for root in roots for candidate in (root / "main" / "main.exe", root / "main.exe")]
    )


def _main_py_path() -> Path:
    return _source_root() / "main.py"


def _launch_file(path: Path) -> Path | None:
    snapshot = _launch_file_snapshot(path)
    return snapshot[0] if snapshot is not None else None


def _launch_file_snapshot(
    path: Path,
) -> tuple[Path, os.stat_result] | None:
    try:
        launch_path = require_regular_file_without_links(
            path,
            field="chat launch file",
        )
        with open_binary_read_without_links(launch_path) as source:
            identity = os.fstat(source.fileno())
        return launch_path, identity
    except (FileNotFoundError, OSError, PermissionError, ValueError):
        return None


def _resolve_chat_launch_asset(
    state: BridgeState,
    raw_path: str,
    *,
    field: str,
) -> str:
    """Resolve one optional launch-time asset to an existing stable path."""

    if not raw_path:
        return ""
    exact = portable_path_text(raw_path, field=field)
    resolved = resolve_runtime_asset_read_path(
        exact,
        root=state_project_root(state),
    )
    return str(
        require_regular_file_without_links(
            resolved,
            field=field,
        )
    )


def _history_launch_snapshots(
    history_path: Path,
) -> tuple[
    tuple[tuple[Path, os.stat_result], ...],
    tuple[tuple[Path, os.stat_result], ...],
]:
    """Capture the exact mutable history container handed to the child."""

    if history_path.suffix.lower() == ".json" and os.path.lexists(history_path):
        file_snapshot = _launch_file_snapshot(history_path)
        if file_snapshot is None:
            raise FileNotFoundError(
                f"chat history file is unavailable: {history_path}"
            )
        parent, parent_identity = capture_directory_identity(
            history_path.parent,
            field="chat history directory",
        )
        return (file_snapshot,), ((parent, parent_identity),)

    session_dir = chat_history_session_dir(history_path)
    session_dir, session_identity = capture_directory_identity(
        session_dir,
        field="chat history session directory",
    )
    return (), ((session_dir, session_identity),)


def _launch_chat(
    state: BridgeState,
    *,
    character_names: list[str] | None = None,
    effect_names: str = "",
    history_file: str,
    init_sprite_path: str,
    room_id: str,
    selected_bg: str,
    system_template: str,
    use_cg: bool,
    user_scenario: str,
    stream_endpoint: str = "",
    init_stream_endpoint: str = "",
    workflow_path: str = "",
) -> str:
    global _main_chat_process

    with _main_chat_process_lock:
        _chat_debug_log(
            f"launch_chat start runtime_mode={_chat_runtime_mode(state)} has_stream_endpoint={bool(stream_endpoint)} history_file={history_file or ''} workflow_path={workflow_path or ''}"
        )
        if _main_chat_process is not None and _main_chat_process.poll() is not None:
            _chat_debug_log(
                f"launch_chat previous_process_exited pid={_main_chat_process.pid} code={_process_return_code(_main_chat_process)}"
            )
            _close_chat_log_if_needed()
        if _main_chat_process is not None and _main_chat_process.poll() is None:
            _chat_debug_log(f"launch_chat skipped reason=already_running pid={_main_chat_process.pid}")
            return f"进程已经在运行中！PID: {_main_chat_process.pid}"

        init_sprite_path = _resolve_chat_launch_asset(
            state,
            init_sprite_path,
            field="initial sprite file",
        )
        workflow_path = _resolve_chat_launch_asset(
            state,
            workflow_path,
            field="chat workflow file",
        )
        launch_asset_snapshots: list[tuple[Path, os.stat_result]] = []
        for asset_path in (init_sprite_path, workflow_path):
            if not asset_path:
                continue
            asset_file = Path(asset_path)
            with open_binary_read_without_links(asset_file) as source:
                launch_asset_snapshots.append(
                    (asset_file, os.fstat(source.fileno()))
                )

        # 把用户情景放在系统模板末尾（紧跟 closing 提示后）
        effective_user_scenario = _effective_user_scenario(user_scenario)
        template = _compose_runtime_template(system_template, effective_user_scenario)
        template_dir = _template_dir(state)
        _write_runtime_template_files(
            template_dir,
            template,
            effective_user_scenario,
            system_template,
        )

        previous_system_config = state.config_manager.config.system_config
        sc = previous_system_config.model_copy(deep=True)
        sc.live_room_id = room_id
        state.config_manager.config.system_config = sc
        try:
            state.config_manager.save_system_config()
        except BaseException:
            state.config_manager.config.system_config = previous_system_config
            raise

        template_hash = _history_id_from_scenario(user_scenario, character_names)
        history_path = resolve_history_path_for_project(
            state,
            history_file if history_file else history_root_for_state(state) / template_hash,
        )
        history_argument = str(history_path)
        if is_unc_history_path(history_path):
            # Never probe or canonicalize an offline UNC share during launch.
            # The child receives the exact lexical network path selected by
            # the user and owns the eventual connection attempt.
            history_file_snapshots = ()
            history_directory_snapshots = ()
        else:
            history_root = history_root_for_state(state)
            if resolved_path_is_within(history_path, history_root):
                history_path = prepare_history_reference_for_launch(
                    state,
                    history_path,
                )
            elif history_path.suffix.lower() == ".json" and history_path.is_file():
                # The child history manager only mutates project-managed
                # storage. Import an explicitly selected legacy file before
                # launch so load, incremental save, clear, and final save all
                # use the same authoritative path.
                history_path = prepare_history_reference_for_launch(
                    state,
                    history_path,
                )
            else:
                chat_history_session_dir(history_path).mkdir(
                    parents=True,
                    exist_ok=True,
                )
            history_argument = str(history_path)
            history_file_snapshots, history_directory_snapshots = (
                _history_launch_snapshots(history_path)
            )
        template_dir, template_dir_identity = capture_directory_identity(
            template_dir,
            field="runtime template directory",
        )
        runtime_template_snapshots: list[tuple[Path, os.stat_result]] = []
        for filename in ("_temp.txt", "_temp_split.json"):
            snapshot = _launch_file_snapshot(template_dir / filename)
            if snapshot is None:
                raise FileNotFoundError(
                    f"runtime template file is unavailable: {template_dir / filename}"
                )
            runtime_template_snapshots.append(snapshot)
        project_root, project_root_identity = capture_directory_identity(
            state_project_root(state),
            field="chat project root",
        )
        app_root, app_root_identity = capture_directory_identity(
            _app_root(state),
            field="chat application root",
        )
        tts_slug = str(state.config_manager.config.api_config.tts_provider or "gpt-sovits").strip() or "gpt-sovits"
        launch_config = {
            "template": "_temp",
            "init_sprite_path": init_sprite_path or "",
            "history": history_argument,
            "bg": selected_bg,
            "effect_names": effect_names,
            "t2i": "ComfyUI" if use_cg else "",
            "room_id": room_id,
            "tts": tts_slug,
        }
        args = [
            "--template=_temp",
            f"--init_sprite_path={init_sprite_path or ''}",
            f"--history={history_argument}",
            f"--bg={selected_bg}",
            f"--effect_names={effect_names}",
            f"--t2i={'ComfyUI' if use_cg else ''}",
            f"--room_id={room_id}",
            f"--tts={tts_slug}",
        ]
        if character_names:
            characters_json = json.dumps(character_names, ensure_ascii=False)
            launch_config["characters"] = characters_json
            args.append(f"--characters={characters_json}")
        if stream_endpoint:
            launch_config["stream_endpoint"] = stream_endpoint
            args.append(f"--stream-endpoint={stream_endpoint}")
        if init_stream_endpoint:
            launch_config["init_stream_endpoint"] = init_stream_endpoint
            args.append(f"--init-stream-endpoint={init_stream_endpoint}")
        if workflow_path:
            launch_config["workflow"] = workflow_path
            args.append(f"--workflow={workflow_path}")
        env = os.environ.copy()
        env[CHAT_LAUNCH_CONFIG_ENV] = json.dumps(
            launch_config,
            ensure_ascii=False,
        )
        env["SHINSEKAI_PROJECT_ROOT"] = str(project_root)
        env["EASYAI_PROJECT_ROOT"] = str(project_root)
        env["SHINSEKAI_APP_ROOT"] = str(app_root)
        # Only bridge-staged uploads are valid attachment inputs. Giving the
        # subprocess the whole project root would let a forged payload read
        # unrelated project configuration or history files.
        attachment_root = managed_project_storage(
            Path(*CHAT_ATTACHMENT_STAGE_SUBDIR),
            root=project_root,
        )
        attachment_root.mkdir(parents=True, exist_ok=True)
        attachment_root = require_directory_without_links(
            attachment_root,
            field="chat attachment root",
        )
        attachment_root, attachment_root_identity = capture_directory_identity(
            attachment_root,
            field="chat attachment root",
        )
        env[CHAT_ATTACHMENTS_ROOT_ENV] = str(attachment_root)
        env["SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG"] = "1"
        api_config = state.config_manager.config.api_config
        env["SHINSEKAI_MEMORY_AUTO_ENABLED"] = "1" if bool(getattr(api_config, "memory_auto_enabled", False)) else "0"
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
            env["SHINSEKAI_MEMORY_SERVICE_URL"] = f"{memory_service_base.rstrip('/')}/api/memory"
            env["SHINSEKAI_MEMORY_SERVICE_OWNER"] = "0"
        if str(getattr(state, "auth_token", "") or "").strip():
            env["SHINSEKAI_MEMORY_SERVICE_TOKEN"] = str(state.auth_token)

        if getattr(sys, "frozen", False):
            candidates = _main_exe_candidates(state)
            executable_snapshot = next(
                (
                    validated
                    for item in candidates
                    if (validated := _launch_file_snapshot(item)) is not None
                ),
                None,
            )
            if executable_snapshot is None:
                checked = " 与 ".join(str(item) for item in candidates)
                _chat_debug_log(f"launch_chat failed reason=main_exe_missing checked={checked}")
                return f"启动失败: 未找到 main.exe（已检查 {checked}）。"
            exe, exe_identity = executable_snapshot
            _main_chat_process, log_path = _popen_chat_process(
                [str(exe)] + args,
                cwd=project_root,
                env=env,
                required_files=(
                    (exe, exe_identity),
                    *launch_asset_snapshots,
                    *runtime_template_snapshots,
                    *history_file_snapshots,
                ),
                required_directories=(
                    (project_root, project_root_identity),
                    (app_root, app_root_identity),
                    (attachment_root, attachment_root_identity),
                    (template_dir, template_dir_identity),
                    *history_directory_snapshots,
                ),
            )
        else:
            main_py_candidate = _main_py_path()
            main_py_snapshot = _launch_file_snapshot(main_py_candidate)
            if main_py_snapshot is None:
                _chat_debug_log(
                    f"launch_chat failed reason=main_py_missing checked={main_py_candidate}"
                )
                return f"启动失败: 未找到 main.py（已检查 {main_py_candidate}）。"
            main_py, main_py_identity = main_py_snapshot
            python_path = resolve_executable_file(
                sys.executable,
                field="chat Python executable",
            )
            python_snapshot = _launch_file_snapshot(python_path)
            if python_snapshot is None:
                return f"启动失败: Python 解释器不可用：{python_path}。"
            python_path, python_identity = python_snapshot
            _main_chat_process, log_path = _popen_chat_process(
                [str(python_path), str(main_py)] + args,
                cwd=project_root,
                env=env,
                required_files=(
                    (python_path, python_identity),
                    (main_py, main_py_identity),
                    *launch_asset_snapshots,
                    *runtime_template_snapshots,
                    *history_file_snapshots,
                ),
                required_directories=(
                    (project_root, project_root_identity),
                    (app_root, app_root_identity),
                    (attachment_root, attachment_root_identity),
                    (template_dir, template_dir_identity),
                    *history_directory_snapshots,
                ),
            )
        try:
            exit_code = _main_chat_process.wait(timeout=1.2)
        except subprocess.TimeoutExpired:
            _chat_debug_log(f"launch_chat running pid={_main_chat_process.pid}")
            return _chat_process_started_message(_main_chat_process)
        _close_chat_log_if_needed()
        _chat_debug_log(f"launch_chat exited_early pid={_main_chat_process.pid} code={exit_code} log_path={log_path}")
        return _failed_launch_message(exit_code, log_path)


def _close_chat(
    state: BridgeState,
    *,
    reason: str = "聊天会话已结束。",
    wait_timeout: float = 4.0,
) -> dict[str, Any]:
    with _chat_transition_lock(state):
        return _close_chat_locked(
            state,
            reason=reason,
            wait_timeout=wait_timeout,
        )


def _close_chat_locked(
    state: BridgeState,
    *,
    reason: str,
    wait_timeout: float,
) -> dict[str, Any]:
    global _main_chat_process

    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    _set_chat_runtime_closing(state, True)
    try:
        _chat_debug_log(f"close_chat start session={session_id} reason={reason} wait_timeout={wait_timeout}")
        graceful_shutdown_requested = False
        if session_id and chat_stream is not None:
            try:
                graceful_shutdown_requested = bool(
                    chat_stream.send_command(
                        session_id,
                        {"cmdId": uuid.uuid4().hex, "type": "close-session"},
                    )
                )
            except Exception:
                graceful_shutdown_requested = False
        shutdown_active_chat_process(
            wait_timeout=wait_timeout,
            wait_before_signal=max(0.0, wait_timeout - 0.7) if graceful_shutdown_requested else 0.0,
        )
        if session_id and chat_stream is not None:
            snapshot = chat_stream.get_snapshot(session_id)
            if not isinstance(snapshot, dict) or not str(snapshot.get("sessionClosedReason") or "").strip():
                chat_stream.close_session(session_id, reason=reason)
        _chat_debug_log(f"close_chat completed session={session_id}")
    finally:
        try:
            stop_mobile_access(state)
        finally:
            _set_chat_runtime_closing(state, False)
    closed_snapshot = _chat_snapshot(state, "idle", "")
    if session_id:
        if chat_stream is not None:
            delete_session = getattr(chat_stream, "delete_session", None)
            if callable(delete_session):
                delete_session(session_id)
        if str(state.chat_session.get("sessionId") or "").strip() == session_id:
            state.chat_session = {**state.chat_session, "sessionId": ""}
    return closed_snapshot


def _resolve_history_file(state: BridgeState, raw_path: str | Path) -> Path:
    return resolve_history_path_for_project(state, raw_path)


def _chat_history_path(state: BridgeState, payload: dict[str, Any], template: dict[str, Any]) -> Path:
    raw = str(payload.get("historyPath") or "")
    if raw:
        path = _resolve_history_file(state, raw)
        if path.name in {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}:
            return _resolve_history_file(state, path.parent)
        if (
            path.suffix.lower() == ".json"
            and not is_unc_history_path(path)
            and not path.is_file()
        ):
            return _resolve_history_file(state, path.with_suffix(""))
        return path
    characters = payload.get("characters")
    if not isinstance(characters, list):
        characters = template.get("selectedCharacters")
    scenario = _scenario_from_template_like(template)
    template_hash = _history_id_from_scenario(scenario, characters)
    return history_root_for_state(state) / template_hash


def _sprite_path(sprite: Any) -> str:
    return str(sprite.path if hasattr(sprite, "path") else sprite.get("path", ""))


def _chat_session_media(state: BridgeState) -> tuple[str, str, list[dict[str, str]]]:
    config = state.config_manager.config
    character_name = str(state.chat_session.get("characterName") or "")
    background_name = str(state.chat_session.get("backgroundName") or "")
    character = state.config_manager.get_character_by_name(character_name) if character_name else None
    background = (
        None
        if _is_transparent_background_name(background_name)
        else state.config_manager.get_background_by_name(background_name)
    )
    if character is None:
        character = config.characters[0] if config.characters else None
    sprites = []
    if character and character.sprites:
        sprite = character.sprites[0]
        sprites.append({"id": f"{character.name}-0", "label": character.name, "path": _sprite_path(sprite)})
    bg_path = ""
    if background and background.sprites:
        sprite = background.sprites[0]
        bg_path = _sprite_path(sprite)
    return bg_path, character.name if character else "", sprites


def _chat_voice_language(state: BridgeState) -> str:
    session_language = str(state.chat_session.get("voiceLanguage") or "").strip().lower()
    if session_language:
        return session_language
    config_manager = getattr(state, "config_manager", None)
    system_config = getattr(getattr(config_manager, "config", None), "system_config", None)
    configured_language = str(getattr(system_config, "voice_language", "") or "").strip().lower()
    return configured_language or "ja"


def _sanitize_user_display_name(value: Any) -> str:
    return sanitize_user_display_name(value)


def _chat_user_display_name(state: BridgeState) -> str:
    return _sanitize_user_display_name(state.chat_session.get("userDisplayName")) or _DEFAULT_USER_DISPLAY_NAME


def _chat_user_display_name_from_snapshot(
    state: BridgeState,
    snapshot: dict[str, Any] | None = None,
) -> str:
    if snapshot is None:
        session_id = str(state.chat_session.get("sessionId") or "").strip()
        chat_stream = getattr(state, "chat_stream", None)
        if session_id and chat_stream is not None:
            candidate = chat_stream.get_snapshot(session_id)
            if isinstance(candidate, dict):
                snapshot = candidate
    stream_name = _sanitize_user_display_name((snapshot or {}).get("userDisplayName"))
    if stream_name:
        state.chat_session = {**state.chat_session, "userDisplayName": stream_name}
        return stream_name
    return _chat_user_display_name(state)


def _history_entry_role_from_text(text: str) -> str:
    raw = str(text or "")
    if "你：" in raw or "你:" in raw:
        return "user"
    if is_option_history_name(raw.split("：", 1)[0].split(":", 1)[0].strip()):
        return "options"
    speaker = normalize_character_name(raw.split("：", 1)[0].split(":", 1)[0].strip())
    if speaker in _SYSTEM_HISTORY_NAMES:
        return "system"
    return "assistant"


def _message_created_at_ms(message: dict[str, Any]) -> int | None:
    for key in ("createdAt", "created_at", "timestamp", "ts"):
        raw = message.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return int(raw * 1000) if raw < 10_000_000_000 else int(raw)
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                continue
            if text.isdigit():
                num = int(text)
                return num * 1000 if num < 10_000_000_000 else num
            try:
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                continue
    return None


def _serialize_history_entries_from_messages(
    messages: Any,
    user_display_name: str = _DEFAULT_USER_DISPLAY_NAME,
) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    entries: list[dict[str, Any]] = []
    user_index = 0
    row_index = 0
    user_name = _sanitize_user_display_name(user_display_name) or _DEFAULT_USER_DISPLAY_NAME
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        if role == "user":
            text = str(message.get("display_content") or message.get("content") or "").strip()
            if not text:
                continue
            entry = {
                "id": f"history-{row_index}",
                "revertUserIndex": user_index,
                "role": "user",
                "text": f"{user_name}: {text}",
            }
            created_at = _message_created_at_ms(message)
            if created_at is not None:
                entry["createdAt"] = created_at
            entries.append(entry)
            user_index += 1
            row_index += 1
            continue
        if role != "assistant":
            continue
        for item in parse_assistant_dialog_content(message.get("content", "")):
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("character_name") or "").strip()
            speech = str(item.get("speech") or "").strip()
            if not speech:
                continue
            plain = f"{speaker}: {speech}" if speaker else speech
            entries.append(
                {
                    "id": f"history-{row_index}",
                    "role": _history_entry_role_from_text(plain),
                    "text": plain,
                }
            )
            row_index += 1
    return entries


def _history_entries_from_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    return [dict(item) for item in (snapshot.get("historyEntries") or []) if isinstance(item, dict)]


def _chat_history_entries(state: BridgeState) -> list[dict[str, Any]]:
    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if session_id and chat_stream is not None:
        snapshot = chat_stream.get_snapshot(session_id)
        if isinstance(snapshot, dict) and "historyEntries" in snapshot:
            entries = _history_entries_from_snapshot(snapshot)
            return entries
    history_raw = str(state.chat_session.get("historyPath") or "")
    if history_raw and is_unc_history_path(history_raw):
        return []
    if history_raw:
        try:
            history_path = _resolve_history_file(state, history_raw)
        except (FileNotFoundError, OSError, PermissionError, ValueError):
            # A stale/corrupt persisted reference must not make the whole chat
            # snapshot unavailable.  Destructive commands resolve separately
            # and still fail closed instead of acting on a guessed path.
            history_path = None
    else:
        history_path = None
    if history_path is not None and is_unc_history_path(history_path):
        return []
    history_file = chat_history_active_path(history_path) if history_path is not None else None
    if history_file is None or not history_file.is_file():
        return []
    return _serialize_history_entries_from_messages(_read_history_file(history_file), _chat_user_display_name(state))


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
    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    voice_language = _chat_voice_language(state)
    runtime_mode = _chat_runtime_mode(state)
    experimental_features = _chat_experimental_features(state)
    user_display_name = _chat_user_display_name(state)
    runtime_state = {
        "chatProcessRunning": _chat_process_running(),
        "chatRuntimeClosing": _chat_runtime_closing(state),
        "turnOptions": _chat_turn_options(state),
    }
    mobile_access_info = get_mobile_access_info(state)
    if mobile_access_info is not None:
        runtime_state["mobileAccess"] = mobile_access_info.to_payload()
    if session_id and chat_stream is not None:
        snapshot = (
            chat_stream.get_snapshot(session_id, renderer_id=renderer_id)
            if renderer_id
            else chat_stream.get_snapshot(session_id)
        )
        if snapshot is not None:
            next_snapshot = dict(snapshot)
            user_display_name = _chat_user_display_name_from_snapshot(state, next_snapshot)
            next_snapshot["runtimeMode"] = runtime_mode
            next_snapshot["experimentalFeatures"] = experimental_features
            next_snapshot["userDisplayName"] = user_display_name
            if not experimental_features["conversationTree"]:
                next_snapshot.pop("conversationTree", None)
            if voice_language and not str(next_snapshot.get("voiceLanguage") or "").strip():
                next_snapshot["voiceLanguage"] = voice_language
            next_snapshot["historyEntries"] = _chat_history_entries(state)
            if message:
                next_snapshot["dialogText"] = message
                next_snapshot.pop("dialogHtml", None)
                next_snapshot["characterName"] = ""
                next_snapshot["statusMessage"] = message
            if status is not None:
                next_snapshot["status"] = status
                next_snapshot["numericInfo"] = status
            next_snapshot.update(runtime_state)
            if mobile_access_info is not None:
                next_snapshot["wsUrl"] = mobile_access_info.websocket_url
            if extra:
                next_snapshot.update(extra)
            return next_snapshot
    bg_path, character_name, sprites = _chat_session_media(state)
    history_path = str(state.chat_session.get("historyPath") or "")
    return {
        "backgroundPath": bg_path,
        "characterName": "" if message else character_name,
        "dialogText": message,
        "eventSeq": 0,
        "historyEntries": _chat_history_entries(state),
        "historyPath": history_path,
        "inputDraft": "",
        "numericInfo": status,
        "options": [],
        "experimentalFeatures": experimental_features,
        "runtimeMode": runtime_mode,
        "sprites": sprites,
        "status": status or "idle",
        "statusMessage": message,
        "userDisplayName": user_display_name,
        "voiceLanguage": voice_language,
        **runtime_state,
        **(extra or {}),
    }


def _chat_stream_initial_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Create a stream snapshot without carrying sprites from a previous session.

    The runtime producer is authoritative for the initial or history-restored
    sprite and will publish it before chat initialization completes.
    """
    initial = dict(snapshot)
    initial["sprites"] = []
    return initial


def _plain_history_text(raw: Any) -> str:
    return history_payload_to_plain_text(raw)


def _plain_history_text_from_entries(entries: list[dict[str, Any]]) -> str:
    return history_payload_to_plain_text(entries)


def _read_history_file(path: Path) -> Any:
    if not path.is_file():
        return []
    return json.loads(read_text_without_links(path))


def _current_chat_history_download_file(state: BridgeState) -> Path:
    history_raw = str(state.chat_session.get("historyPath") or "")
    if not history_raw:
        raise FileNotFoundError("没有已关联的聊天历史文件。")
    history_path = _resolve_history_file(state, history_raw)
    history_file = chat_history_download_path(history_path)
    if not history_file.is_file():
        raise FileNotFoundError(history_file.as_posix())
    return history_file


def _history_download_state(state: BridgeState) -> tuple[threading.Lock, dict[str, tuple[str, float]]]:
    lock = getattr(state, "history_download_lock", None)
    if lock is None:
        lock = threading.Lock()
        setattr(state, "history_download_lock", lock)
    capabilities = getattr(state, "history_download_capabilities", None)
    if not isinstance(capabilities, dict):
        capabilities = {}
        setattr(state, "history_download_capabilities", capabilities)
    return lock, capabilities


def _issue_chat_history_download_capability(state: BridgeState, history_file: Path) -> str:
    capability = uuid.uuid4().hex
    lock, capabilities = _history_download_state(state)
    with lock:
        # Only the latest requested history download remains valid.
        capabilities.clear()
        capabilities[capability] = (
            str(history_file),
            time.monotonic() + _HISTORY_DOWNLOAD_CAPABILITY_TTL_SECONDS,
        )
    return capability


def _chat_history_download_file(state: BridgeState, capability: str) -> Path:
    supplied = reject_control_chars(
        str(capability or "").strip(),
        field="history download capability",
    )
    if not supplied:
        raise PermissionError("missing chat history download capability")
    lock, capabilities = _history_download_state(state)
    now = time.monotonic()
    with lock:
        expired = [token for token, (_path, deadline) in capabilities.items() if deadline < now]
        for token in expired:
            capabilities.pop(token, None)
        record = capabilities.get(supplied)
    if record is None:
        raise PermissionError("invalid or expired chat history download capability")
    history_file = Path(record[0])
    if not history_file.is_file():
        raise FileNotFoundError(history_file.as_posix())
    return history_file


def _handle_chat_command(state: BridgeState, body: dict[str, Any]) -> dict[str, Any]:
    command = str(body.get("type") or "").strip()
    history_raw = str(state.chat_session.get("historyPath") or "")
    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)

    def _forward_runtime_command(
        next_status: str,
        next_message: str = "",
        *,
        session_patch: dict[str, Any] | None = None,
        snapshot_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if command not in _RUNTIME_CHAT_COMMANDS:
            raise ValueError(f"未知实时聊天命令：{command}")
        if not session_id or chat_stream is None:
            raise RuntimeError("当前聊天会话未连接到实时流。")
        runtime_command = dict(body)
        runtime_command["cmdId"] = str(body.get("cmdId") or uuid.uuid4().hex)
        if not chat_stream.send_command(session_id, runtime_command):
            raise RuntimeError("实时聊天会话未就绪，无法发送命令。")
        if session_patch:
            state.chat_session = {**state.chat_session, **session_patch}
        next_snapshot = {
            "numericInfo": next_status,
            "sessionClosedReason": "",
            "status": next_status,
        }
        current_snapshot = chat_stream.get_snapshot(session_id)
        if isinstance(current_snapshot, dict) and str(current_snapshot.get("sessionClosedReason") or "").strip():
            next_snapshot["notificationText"] = ""
        if next_message:
            next_snapshot["dialogText"] = next_message
            next_snapshot["dialogHtml"] = None
            next_snapshot["characterName"] = ""
        if snapshot_patch:
            next_snapshot.update(snapshot_patch)
        chat_stream.update_session_snapshot(session_id, next_snapshot)
        return _chat_snapshot(state, next_status, next_message, extra=snapshot_patch)

    def _current_runtime_status() -> str:
        if session_id and chat_stream is not None:
            snapshot = chat_stream.get_snapshot(session_id)
            if isinstance(snapshot, dict):
                status = str(snapshot.get("status") or "").strip()
                if status:
                    return status
        return "idle"

    if command == "copy-history":
        entries = _chat_history_entries(state)
        text = _plain_history_text_from_entries(entries)
        opened_path = history_raw
        if not text:
            if not history_raw:
                raise FileNotFoundError("没有已关联的聊天历史文件。")
            history_path = _resolve_history_file(state, history_raw)
            history_file = chat_history_active_path(history_path)
            if not history_file.exists():
                raise FileNotFoundError(history_file.as_posix())
            text = _plain_history_text(_read_history_file(history_file))
            opened_path = history_file.as_posix()
        return _chat_snapshot(
            state,
            "idle",
            "历史记录已复制。",
            extra={"clipboardText": text, "openedPath": opened_path},
        )

    if command == "open-history":
        history_file = _current_chat_history_download_file(state)
        capability = _issue_chat_history_download_capability(state, history_file)
        return _chat_snapshot(
            state,
            "idle",
            "历史文件已打开。",
            extra={
                "downloadUrl": f"/api/chat/history-file?cap={quote(capability, safe='')}",
                "openedPath": history_file.as_posix(),
            },
        )

    if command == "clear-history":
        if session_id and chat_stream is not None:
            return _forward_runtime_command(
                "idle",
                "历史记录已经清空。",
                snapshot_patch={"historyEntries": [], "options": []},
            )
        if not history_raw:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        history_path = _resolve_history_file(state, history_raw)
        try:
            history_root = history_root_for_state(state)
        except (OSError, PermissionError, RuntimeError, ValueError):
            history_root = None
        if (
            history_root is not None
            and resolved_path_is_within(history_path, history_root)
        ):
            remove_chat_history_storage(history_path, root=history_root)
        else:
            # Explicit external sessions are cleared in place, but the
            # storage helper removes only Shinsekai's reserved files and
            # preserves unrelated content.
            remove_chat_history_storage(history_path)
        return _chat_snapshot(state, "idle", "历史记录已经清空。", extra={"historyEntries": [], "options": []})

    if command == "dismiss-plugin-page":
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Plugin page dismissal must be an object.")
        plugin_id = reject_control_chars(
            str(payload.get("pluginId") or "").strip(),
            field="pluginId",
        )
        presentation_id = reject_control_chars(
            str(payload.get("presentationId") or "").strip(),
            field="presentationId",
        )
        if not plugin_id or not presentation_id:
            raise ValueError("Plugin page dismissal requires pluginId and presentationId.")
        if len(plugin_id) > 128 or len(presentation_id) > 128:
            raise ValueError("Plugin page dismissal identifiers are too long.")
        body["payload"] = {
            "pluginId": plugin_id,
            "presentationId": presentation_id,
        }
        if not session_id or chat_stream is None:
            raise RuntimeError("当前聊天会话未连接到实时流。")
        if not chat_stream.publish_event(
            session_id,
            {
                "type": "plugin.page.dismiss",
                "pluginId": plugin_id,
                "presentationId": presentation_id,
            },
        ):
            raise RuntimeError("无法关闭插件页面展示。")
        return _chat_snapshot(state, _current_runtime_status())

    if command == "update-turn-options":
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Chat turn options must be an object.")
        interrupt_enabled = payload.get("interruptEnabled")
        batch_enabled = payload.get("batchEnabled")
        batch_idle_seconds = payload.get("batchIdleSeconds")
        if not isinstance(interrupt_enabled, bool) or not isinstance(batch_enabled, bool):
            raise ValueError("Chat turn switches must be boolean values.")
        if isinstance(batch_idle_seconds, bool) or not isinstance(batch_idle_seconds, (int, float)):
            raise ValueError("Batch input timeout must be numeric.")
        timeout = float(batch_idle_seconds)
        if not 0.3 <= timeout <= 120.0:
            raise ValueError("Batch input timeout must be between 0.3 and 120 seconds.")

        config_manager = state.config_manager
        previous = config_manager.config.api_config
        updated = previous.model_copy(deep=True)
        updated.interrupt_enabled = interrupt_enabled
        updated.is_batch_input_enabled = batch_enabled
        updated.batch_input_timeout = timeout
        config_manager.config.api_config = updated
        try:
            config_manager.save_api_config()
            turn_options = _chat_turn_options(state)
            return _forward_runtime_command(
                _current_runtime_status(),
                snapshot_patch={"turnOptions": turn_options},
            )
        except Exception:
            config_manager.config.api_config = previous
            try:
                config_manager.save_api_config()
            except Exception:
                pass
            raise

    if command in {"chat-input-state", "flush-input-batch", "cancel-input-batch"}:
        return _forward_runtime_command(_current_runtime_status())

    if command == "submit-option" and isinstance(body.get("payload"), dict):
        payload = body["payload"]
        if payload.get("kind") != "tool-confirmation":
            raise ValueError("Option selection must be a string.")
        confirmation_id = reject_control_chars(
            str(payload.get("confirmationId") or "").strip(),
            field="confirmationId",
        )
        action = str(payload.get("action") or "").strip().casefold()
        if (
            not confirmation_id
            or len(confirmation_id) > 128
            or action not in {"confirm", "cancel"}
        ):
            raise ValueError("Tool confirmation response is invalid.")
        body["payload"] = {
            "action": action,
            "confirmationId": confirmation_id,
            "kind": "tool-confirmation",
        }
        return _forward_runtime_command(_current_runtime_status())

    if command == "audio-playback-signal":
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Audio playback signal must be an object.")
        playback_id = reject_control_chars(
            str(payload.get("playbackId") or "").strip(),
            field="playbackId",
        )
        renderer_id = reject_control_chars(
            str(payload.get("rendererId") or "").strip(),
            field="rendererId",
        )
        playback_state = str(payload.get("state") or "").strip()
        if not playback_id or not renderer_id or playback_state not in {
            "started",
            "finished",
            "interrupted",
            "failed",
        }:
            raise ValueError("Audio playback signal is invalid.")
        body["payload"] = {
            "playbackId": playback_id,
            "rendererId": renderer_id[:128],
            "state": playback_state,
            "error": str(payload.get("error") or "")[:500],
        }
        return _forward_runtime_command(_current_runtime_status())

    if command in {"send-message", "submit-option"}:
        attachments = []
        payload = body.get("payload")
        if command == "send-message" and isinstance(payload, dict):
            submitted_text = str(payload.get("text") or "").strip()
            raw_attachments = payload.get("attachments")
            if isinstance(raw_attachments, list) and raw_attachments:
                attachment_root = managed_project_storage(
                    Path(*CHAT_ATTACHMENT_STAGE_SUBDIR),
                    root=state_project_root(state),
                )
                attachments = resolve_chat_attachments(
                    raw_attachments,
                    root=attachment_root,
                )
            body["payload"] = {
                "attachments": [attachment.to_payload() for attachment in attachments],
                "text": submitted_text,
            }
        else:
            submitted_text = str(payload or "").strip()
        if not submitted_text and not attachments:
            raise ValueError("选项不能为空。" if command == "submit-option" else "消息内容不能为空。")
        if _chat_turn_options(state)["batchEnabled"]:
            snapshot_patch: dict[str, Any] = {"inputDraft": ""}
            if command == "send-message":
                snapshot_patch["userDisplayName"] = _chat_user_display_name_from_snapshot(state)
            return _forward_runtime_command(
                _current_runtime_status(),
                snapshot_patch=snapshot_patch,
            )
        if command == "submit-option":
            return _forward_runtime_command("generating", f"已选择：{submitted_text}")
        user_display_name = _chat_user_display_name_from_snapshot(state)
        return _forward_runtime_command(
            "generating",
            chat_attachment_display_text(submitted_text, attachments),
            snapshot_patch={
                "characterName": user_display_name,
                "inputDraft": "",
                "userDisplayName": user_display_name,
            },
        )

    if command == "skip-speech":
        return _forward_runtime_command("idle", "已跳过当前语音。")
    if command == "dialog-advance":
        return _forward_runtime_command("idle")
    if command == "change-voice-language":
        voice_language = str(body.get("payload") or "").strip().lower()
        if not voice_language:
            raise ValueError("语音语言不能为空。")
        return _forward_runtime_command(
            "idle",
            session_patch={"voiceLanguage": voice_language},
            snapshot_patch={"voiceLanguage": voice_language},
        )
    if command == "pause-asr":
        return _forward_runtime_command("paused", "语音识别已暂停。")
    if command == "resume-asr":
        return _forward_runtime_command("listening", "语音识别已恢复。")
    if command == "reroll":
        return _forward_runtime_command("generating", "正在请求重新生成。")
    if command == "revert-history":
        try:
            int(body.get("payload"))
        except (TypeError, ValueError) as exc:
            raise ValueError("回溯索引无效。") from exc
        return _forward_runtime_command("idle")
    if command == "fork-history":
        if not _chat_experimental_features(state)["forkHistory"]:
            raise PermissionError("React Chat UI Fork 实验功能未启用。")
        payload = body.get("payload")
        raw_index = payload.get("userIndex") if isinstance(payload, dict) else payload
        try:
            int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("分支索引无效。") from exc
        return _forward_runtime_command("generating", "正在创建对话分支。")
    if command == "switch-branch":
        if not _chat_experimental_features(state)["conversationTree"]:
            raise PermissionError("React Chat UI 分支流程图实验功能未启用。")
        branch_id = str(body.get("payload") or "").strip()
        if not branch_id:
            raise ValueError("分支 id 不能为空。")
        return _forward_runtime_command("idle", "已切换对话分支。")
    if command == "rename-branch":
        if not _chat_experimental_features(state)["conversationTree"]:
            raise PermissionError("React Chat UI 分支流程图实验功能未启用。")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("分支重命名参数无效。")
        branch_id = str(payload.get("branchId") or "").strip()
        label = str(payload.get("label") or "").strip()
        if not branch_id:
            raise ValueError("分支 id 不能为空。")
        if not label:
            raise ValueError("分支名称不能为空。")
        return _forward_runtime_command("idle", "已重命名对话分支。")

    raise ValueError(f"未知聊天命令：{command}")


def _chat_theme_payload(state: BridgeState) -> dict[str, Any]:
    system_config = state.config_manager.config.system_config
    raw_path = str(system_config.chat_ui_theme_path or "")
    path = resolve_from_root(
        raw_path or "data/chat_ui_theme.json",
        state_project_root(state),
    )
    data: Any = {}
    if path.is_file():
        parsed = json.loads(read_text_without_links(path))
        if isinstance(parsed, dict):
            data = parsed
    return {
        "path": path.as_posix() if path.exists() else "",
        "raw": data,
        "themeColor": str(system_config.theme_color or ""),
    }

"""Manage the chat subprocess, runtime paths, locks and launch diagnostics."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from core.paths import app_root as runtime_app_root
from core.paths import project_root as runtime_project_root
from core.paths import source_root as runtime_source_root
from core.media.chat_attachments import CHAT_ATTACHMENTS_ROOT_ENV
from core.chat_history.storage import chat_history_session_dir
from application.chat.history_paths import is_unc_history_path
from application.chat.build_effect_context import SelectedEffectContext
from application.chat.templates import (
    TEMP_SPLIT_META,
    _compose_runtime_template,
    _effective_user_scenario,
    _history_id_from_scenario,
    _template_dir,
)
from application.runtime.dependencies import runtime_dependency_error_from_text
from application.runtime.state import BridgeState
from application.chat.launch_args import CHAT_LAUNCH_CONFIG_ENV

_main_chat_process: subprocess.Popen[bytes] | None = None
_main_chat_process_lock = threading.Lock()
_main_chat_log_file: Any = None


def _chat_runtime_mode(_state: BridgeState) -> str:
    """Return the only supported chat UI runtime."""
    return "react"


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {"start_new_session": True}
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    }


def _chat_process_running() -> bool:
    with _main_chat_process_lock:
        return _main_chat_process is not None and _main_chat_process.poll() is None


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


def _chat_log_path() -> Path:
    log_dir = _project_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "main.log"


def _tail_text(path: Path, max_chars: int = 2400) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
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


def _popen_chat_process(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> tuple[subprocess.Popen[bytes], Path]:
    global _main_chat_log_file
    _close_chat_log_if_needed()
    log_path = _chat_log_path()
    _main_chat_log_file = log_path.open("a", encoding="utf-8", buffering=1)
    _main_chat_log_file.write(
        "\n"
        + "=" * 60
        + f"\n{datetime.now().isoformat(sep=' ', timespec='seconds')}  main.py launch\n"
        + f"cwd: {cwd}\n"
        + f"cmd: {' '.join(cmd)}\n"
    )
    env = {**env, "PYTHONUNBUFFERED": "1"}
    # The command contains only the trusted interpreter/entrypoint. Runtime
    # options are delivered through a validated JSON environment payload.
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=_main_chat_log_file,
        stderr=subprocess.STDOUT,
        **_hidden_subprocess_kwargs(),
    )
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
        return

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
            return


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
        [candidate for root in roots for candidate in (root / "main" / "main.exe", root / "main.exe")]
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
    global _main_chat_process

    with _main_chat_process_lock:
        if _main_chat_process is not None and _main_chat_process.poll() is not None:
            _close_chat_log_if_needed()
        if _main_chat_process is not None and _main_chat_process.poll() is None:
            return f"进程已经在运行中！PID: {_main_chat_process.pid}"

        # 把用户情景放在系统模板末尾（紧跟 closing 提示后）
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
            json.dumps({"scenario": effective_user_scenario, "system": system_template}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        sc = state.config_manager.config.system_config.model_copy(deep=True)
        sc.live_room_id = room_id
        state.config_manager.config.system_config = sc
        state.config_manager.save_system_config()

        template_hash = _history_id_from_scenario(user_scenario, character_names)
        history_path = Path(history_file) if history_file else Path(state.history_dir) / template_hash
        history_argument = str(history_path)
        if not is_unc_history_path(history_path):
            if history_path.suffix.lower() == ".json" and history_path.exists() and history_path.is_file():
                history_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                chat_history_session_dir(history_path).mkdir(parents=True, exist_ok=True)
            history_argument = str(history_path.resolve())
        project_root = _project_root()
        app_root = _app_root(state)
        tts_slug = str(state.config_manager.config.api_config.tts_provider or "gpt-sovits").strip() or "gpt-sovits"
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
            launch_config["characters"] = json.dumps(character_names, ensure_ascii=False)
        if player_name:
            launch_config["player_character"] = player_name
            launch_config["read_player_speech"] = read_player_speech
            launch_config["allow_player_dialogue"] = bool(chat_session.get("allowPlayerDialogue", True))
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
        attachment_root = os.environ.get(CHAT_ATTACHMENTS_ROOT_ENV, "").strip() or str(project_root)
        os.environ.setdefault(CHAT_ATTACHMENTS_ROOT_ENV, attachment_root)
        env[CHAT_ATTACHMENTS_ROOT_ENV] = attachment_root
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
            exe = next((item for item in candidates if item.is_file()), None)
            if exe is None:
                checked = " 与 ".join(str(item) for item in candidates)
                return f"启动失败: 未找到 main.exe（已检查 {checked}）。"
            _main_chat_process, log_path = _popen_chat_process([str(exe)], cwd=project_root, env=env)
        else:
            main_py = _main_py_path()
            if not main_py.is_file():
                return f"启动失败: 未找到 main.py（已检查 {main_py}）。"
            _main_chat_process, log_path = _popen_chat_process(
                [sys.executable, str(main_py)],
                cwd=project_root,
                env=env,
            )
        try:
            exit_code = _main_chat_process.wait(timeout=1.2)
        except subprocess.TimeoutExpired:
            return _chat_process_started_message(_main_chat_process)
        _close_chat_log_if_needed()
        return _failed_launch_message(exit_code, log_path)

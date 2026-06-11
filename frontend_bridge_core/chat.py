from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.paths import app_root as runtime_app_root
from core.paths import project_root as runtime_project_root
from core.paths import source_root as runtime_source_root

from .state import BridgeState
from .runtime_dependencies import runtime_dependency_error_from_text
from .templates import (
    TEMP_SPLIT_META,
    _compose_for_llm,
    _history_id_from_scenario,
    _template_dir,
)

TRANSPARENT_BACKGROUND_NAME = "透明场景"
_main_chat_process: subprocess.Popen[bytes] | None = None
_main_chat_process_lock = threading.Lock()
_main_chat_log_file: Any = None


def _hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


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
    effect_names: str = "",
    history_file: str,
    init_sprite_path: str,
    room_id: str,
    selected_bg: str,
    system_template: str,
    use_cg: bool,
    user_scenario: str,
) -> str:
    global _main_chat_process

    with _main_chat_process_lock:
        if _main_chat_process is not None and _main_chat_process.poll() is not None:
            _close_chat_log_if_needed()
        if _main_chat_process is not None and _main_chat_process.poll() is None:
            return f"进程已经在运行中！PID: {_main_chat_process.pid}"

        template = _compose_for_llm(user_scenario, system_template)
        template_dir = _template_dir(state)
        (template_dir / "_temp.txt").write_text(template, encoding="utf-8")
        (template_dir / TEMP_SPLIT_META).write_text(
            json.dumps({"scenario": user_scenario, "system": system_template}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        sc = state.config_manager.config.system_config.model_copy(deep=True)
        sc.live_room_id = room_id
        state.config_manager.config.system_config = sc
        state.config_manager.save_system_config()

        template_hash = _history_id_from_scenario(user_scenario, system_template)
        history_path = Path(history_file) if history_file else Path(state.history_dir) / f"{template_hash}.json"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        project_root = _project_root()
        app_root = _app_root(state)
        tts_slug = str(state.config_manager.config.api_config.tts_provider or "gpt-sovits").strip() or "gpt-sovits"
        args = [
            "--template=_temp",
            f"--init_sprite_path={init_sprite_path or ''}",
            f"--history={history_path.resolve()}",
            f"--bg={selected_bg}",
            f"--effect_names={effect_names}",
            f"--t2i={'ComfyUI' if use_cg else ''}",
            f"--room_id={room_id}",
            f"--tts={tts_slug}",
        ]
        env = os.environ.copy()
        env["EASYAI_PROJECT_ROOT"] = str(project_root)
        env["SHINSEKAI_APP_ROOT"] = str(app_root)
        env["SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG"] = "1"

        if getattr(sys, "frozen", False):
            candidates = _main_exe_candidates(state)
            exe = next((item for item in candidates if item.is_file()), None)
            if exe is None:
                checked = " 与 ".join(str(item) for item in candidates)
                return f"启动失败: 未找到 main.exe（已检查 {checked}）。"
            _main_chat_process, log_path = _popen_chat_process([str(exe)] + args, cwd=project_root, env=env)
        else:
            main_py = _main_py_path()
            if not main_py.is_file():
                return f"启动失败: 未找到 main.py（已检查 {main_py}）。"
            _main_chat_process, log_path = _popen_chat_process(
                [sys.executable, str(main_py)] + args,
                cwd=project_root,
                env=env,
            )
        try:
            exit_code = _main_chat_process.wait(timeout=1.2)
        except subprocess.TimeoutExpired:
            return f"聊天进程已启动！PID: {_main_chat_process.pid}"
        _close_chat_log_if_needed()
        return _failed_launch_message(exit_code, log_path)


def _resolve_project_file(raw_path: str | Path) -> Path:
    root = Path.cwd().resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if root not in path.parents and path != root:
        raise PermissionError("path is outside project root")
    return path


def _chat_history_path(state: BridgeState, payload: dict[str, Any], template: dict[str, Any]) -> Path:
    raw = str(payload.get("historyPath") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    template_hash = _history_id_from_scenario(
        str(template.get("scenario") or template.get("content") or ""),
        str(template.get("system") or ""),
    )
    return _resolve_project_file(Path(state.history_dir) / f"{template_hash}.json")


def _sprite_path(sprite: Any) -> str:
    return str(sprite.path if hasattr(sprite, "path") else sprite.get("path", ""))


def _chat_session_media(state: BridgeState) -> tuple[str, str, list[dict[str, str]]]:
    config = state.config_manager.config
    character_name = str(state.chat_session.get("characterName") or "")
    background_name = str(state.chat_session.get("backgroundName") or "")
    character = state.config_manager.get_character_by_name(character_name) if character_name else None
    background = state.config_manager.get_background_by_name(background_name) if background_name else None
    if character is None:
        character = config.characters[0] if config.characters else None
    if background is None:
        background = config.background_list[0] if config.background_list else None
    sprites = []
    if character and character.sprites:
        sprite = character.sprites[0]
        sprites.append({"id": f"{character.name}-0", "label": character.name, "path": _sprite_path(sprite)})
    bg_path = ""
    if background and background.sprites:
        sprite = background.sprites[0]
        bg_path = _sprite_path(sprite)
    return bg_path, character.name if character else "", sprites


def _chat_snapshot(
    state: BridgeState,
    status: str = "idle",
    message: str = "",
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bg_path, character_name, sprites = _chat_session_media(state)
    history_path = str(state.chat_session.get("historyPath") or "")
    return {
        "backgroundPath": bg_path,
        "characterName": character_name,
        "dialogText": message or "React bridge 已连接，启动聊天后主进程会接管实时演出窗口。",
        "historyPath": history_path,
        "inputDraft": "",
        "numericInfo": status,
        "options": [],
        "sprites": sprites,
        "status": status,
        **(extra or {}),
    }


def _plain_history_text(raw: Any) -> str:
    if not isinstance(raw, list):
        return ""
    rows: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
            if content:
                rows.append(f"{role}: {content}" if role else content)
        else:
            text = re.sub(r"<[^>]+>", "", str(item)).strip()
            if text:
                rows.append(text)
    return "\n".join(rows)


def _read_history_file(path: Path) -> Any:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _handle_chat_command(state: BridgeState, body: dict[str, Any]) -> dict[str, Any]:
    command = str(body.get("type") or "").strip()
    history_raw = str(state.chat_session.get("historyPath") or "").strip()
    history_path = _resolve_project_file(history_raw) if history_raw else None

    if command == "copy-history":
        if history_path is None:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        if not history_path.exists():
            raise FileNotFoundError(history_path.as_posix())
        text = _plain_history_text(_read_history_file(history_path))
        return _chat_snapshot(
            state,
            "idle",
            "历史记录已复制。",
            extra={"clipboardText": text, "openedPath": history_path.as_posix()},
        )

    if command == "open-history":
        if history_path is None:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        if not history_path.exists():
            raise FileNotFoundError(history_path.as_posix())
        rel = history_path.relative_to(Path.cwd().resolve()).as_posix()
        return _chat_snapshot(
            state,
            "idle",
            "历史文件已打开。",
            extra={"downloadUrl": f"/api/download?path={quote(rel)}", "openedPath": rel},
        )

    if command == "clear-history":
        if history_path is None:
            raise FileNotFoundError("没有已关联的聊天历史文件。")
        history_path.unlink(missing_ok=True)
        return _chat_snapshot(state, "idle", "历史记录已经清空。")

    if command == "send-message":
        text = str(body.get("payload") or "").strip()
        if not text:
            raise ValueError("消息内容不能为空。")
        return _chat_snapshot(state, "generating", f"已提交：{text}")

    if command == "submit-option":
        option = str(body.get("payload") or "").strip()
        if not option:
            raise ValueError("选项不能为空。")
        return _chat_snapshot(state, "generating", f"已选择：{option}")

    if command == "skip-speech":
        return _chat_snapshot(state, "idle", "已跳过当前语音。")
    if command == "pause-asr":
        return _chat_snapshot(state, "paused", "语音识别已暂停。")
    if command == "reroll":
        return _chat_snapshot(state, "generating", "正在请求重新生成。")

    raise ValueError(f"未知聊天命令：{command}")


def _chat_theme_payload(state: BridgeState) -> dict[str, Any]:
    system_config = state.config_manager.config.system_config
    raw_path = str(system_config.chat_ui_theme_path or "").strip()
    path = Path(raw_path) if raw_path else Path("data") / "chat_ui_theme.json"
    if not path.is_absolute():
        path = Path.cwd() / path
    data: Any = {}
    if path.is_file():
        with path.open(encoding="utf-8") as file:
            parsed = json.load(file)
        if isinstance(parsed, dict):
            data = parsed
    return {
        "path": path.as_posix() if path.exists() else "",
        "raw": data,
        "themeColor": str(system_config.theme_color or ""),
    }

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .state import BridgeState
from .templates import (
    TEMP_SPLIT_META,
    _compose_for_llm,
    _has_untranslated_template_keys,
    _history_id_from_scenario,
    _latest_history_json,
    _list_templates,
    _parse_stored_template,
    _repair_template_session_if_needed,
    _resume_template_parts,
    _template_dir,
)

TRANSPARENT_BACKGROUND_NAME = "透明场景"
_main_chat_process: subprocess.Popen[bytes] | None = None


def _release_root() -> Path:
    if os.environ.get("EASYAI_PROJECT_ROOT"):
        return Path(os.environ["EASYAI_PROJECT_ROOT"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent


def _launch_chat(
    state: BridgeState,
    *,
    history_file: str,
    init_sprite_path: str,
    room_id: str,
    selected_bg: str,
    system_template: str,
    use_cg: bool,
    user_scenario: str,
) -> str:
    global _main_chat_process

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

    if _main_chat_process is not None and _main_chat_process.poll() is None:
        return f"进程已经在运行中！PID: {_main_chat_process.pid}"

    template_hash = _history_id_from_scenario(user_scenario, system_template)
    history_path = Path(history_file) if history_file else Path(state.history_dir) / f"{template_hash}.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    root = _release_root()
    tts_slug = str(state.config_manager.config.api_config.tts_provider or "gpt-sovits").strip() or "gpt-sovits"
    args = [
        "--template=_temp",
        f"--init_sprite_path={init_sprite_path or ''}",
        f"--history={history_path.resolve()}",
        f"--bg={selected_bg}",
        f"--t2i={'ComfyUI' if use_cg else ''}",
        f"--room_id={room_id}",
        f"--tts={tts_slug}",
    ]

    if getattr(sys, "frozen", False):
        candidates = [root / "main" / "main.exe", root / "main.exe"]
        exe = next((item for item in candidates if item.is_file()), None)
        if exe is None:
            checked = " 与 ".join(str(item) for item in candidates)
            return f"启动失败: 未找到 main.exe（已检查 {checked}）。"
        _main_chat_process = subprocess.Popen([str(exe)] + args, cwd=str(root))
    else:
        main_py = root / "main.py"
        if not main_py.is_file():
            return f"启动失败: 未找到 main.py（已检查 {main_py}）。"
        _main_chat_process = subprocess.Popen([sys.executable, str(main_py)] + args, cwd=str(root))
    return f"聊天进程已启动！PID: {_main_chat_process.pid}"


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

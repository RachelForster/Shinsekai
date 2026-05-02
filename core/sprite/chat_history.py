"""Chat history state and helpers used by main and UI workers."""

from __future__ import annotations

import re
from typing import Any

from llm.history_manager import HistoryManager, parse_assistant_dialog_content

from core.messaging.dialog_tokens import is_option_history_name, is_option_history_plain
from core.messaging.message import TTSOutputMessage

CHAT_HISTORY_PATH = "./data/chat_history"

chat_history: list[Any] = []
history_manager = HistoryManager(chat_history)


def get_history() -> list[Any]:
    """获取聊天历史记录。"""
    return history_manager.get_history()


def getHistory() -> list[Any]:
    """兼容旧名称。"""
    return get_history()


def save_chat_history(file_path: str, history: Any) -> None:
    """根据提供的文件名保存聊天记录到 JSON 文件。"""
    history_manager.save_chat_history(file_path, history)


def load_chat_history(file_path: str) -> Any:
    return history_manager.load_chat_history(file_path)


def clear_chat_history(history_file: str, ui_queue: Any, llm_manager: Any) -> None:
    from i18n import tr

    history_manager.clear_chat_history(history_file)
    llm_manager.clear_messages()
    ui_queue.put(
        TTSOutputMessage(
            audio_path="",
            character_name=tr("main.system_name"),
            speech=tr("main.history_cleared"),
            sprite="-1",
            is_system_message=False,
        )
    )


def copy_chat_history_to_clipboard() -> None:
    """将聊天记录复制到系统剪贴板，去除 HTML 标签并格式化为纯文本。"""
    history_manager.copy_chat_history_to_clipboard()


def replay_history_entry(window: Any, history_entry: str) -> None:
    """回放一条历史记录。若为选项则重新显示选项。"""
    if not history_entry:
        return

    plain_text = re.sub(r"<[^>]+>", "", history_entry).strip()
    name = ""
    content = plain_text
    if "：" in plain_text:
        name, content = plain_text.split("：", 1)
    elif ":" in plain_text:
        name, content = plain_text.split(":", 1)

    if is_option_history_name(name):
        option_list = [item.strip() for item in content.split("/") if item.strip()]
        window.setOptions(option_list)
    else:
        window.setDisplayWords(history_entry)


def is_option_history_entry(history_entry: str) -> bool:
    if not isinstance(history_entry, str):
        return False
    plain_text = re.sub(r"<[^>]+>", "", history_entry).strip()
    return is_option_history_plain(plain_text)


def is_user_history_entry(history_entry: str) -> bool:
    if not isinstance(history_entry, str):
        return False
    return "你</b>" in history_entry or "你</b>：" in history_entry or "你</b>:" in history_entry


def extract_valid_dialog_from_messages(messages: list) -> list:
    """从历史消息中提取最后一条可用 assistant dialog。"""
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content", "")
        dialog = parse_assistant_dialog_content(content)
        if dialog:
            return dialog
    return []


def revert_chat_history(user_index: int, llm_manager: Any, hist: list, window: Any) -> None:
    """按 user_index 回溯到该用户消息之前的上一条 assistant 记录。"""
    if user_index < 0:
        return

    current_user_idx = -1
    user_history_pos = -1
    for idx, entry in enumerate(hist):
        if is_user_history_entry(entry):
            current_user_idx += 1
            if current_user_idx == user_index:
                user_history_pos = idx
                break

    if user_history_pos == -1:
        return

    target_index = -1
    for idx in range(user_history_pos - 1, -1, -1):
        if not is_user_history_entry(hist[idx]):
            target_index = idx
            break

    if target_index < 0:
        return

    del hist[target_index + 1:]

    messages = llm_manager.get_messages()
    if not messages:
        return

    new_messages = []
    current_user_idx = -1
    for message in messages:
        role = message.get("role")
        if role == "user":
            current_user_idx += 1
            if current_user_idx >= user_index:
                break
        new_messages.append(message)

    llm_manager.set_messages(new_messages)

    if hist:
        replay_history_entry(window, hist[-1])


def save_bg(bg_path: str | None, bgm_path: str | None) -> None:
    from config.config_manager import ConfigManager

    config = ConfigManager()
    config.config.system_config.background_path = bg_path
    config.config.system_config.bgm_path = bgm_path
    config.save_system_config()

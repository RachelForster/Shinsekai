import traceback
from typing import Any, Optional
from pathlib import Path
import json
import os
import re
import threading

from sdk.file_transactions import (
    atomic_write_text,
    open_binary_read_without_links,
    open_text_append_without_links,
    read_text_without_links,
    remove_file_without_links,
)
from core.paths import managed_project_storage, path_is_link_or_reparse_point
from core.sprite.chat_branch_storage import validate_chat_history_removal_target
from core.sprite.chat_history_text import _repair_json_string, parse_assistant_dialog_content

# 模块级写锁，保证临时文件写入的线程安全
_tmp_write_lock = threading.Lock()


def _write_json_atomic(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
    )


def _managed_history_file_path(history_file: str | os.PathLike[str]) -> Path:
    """Resolve one JSON history file inside the authoritative history store."""

    history_root = managed_project_storage("data/chat_history")
    candidate = validate_chat_history_removal_target(history_file, history_root)
    if candidate.suffix.lower() != ".json":
        raise ValueError("chat history path must identify a JSON file")
    if path_is_link_or_reparse_point(candidate):
        raise PermissionError("chat history file must not be a symbolic link")
    return candidate


class HistoryManager:
    _instance: Optional['HistoryManager'] = None

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(HistoryManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, chat_history):
        self.chat_history = chat_history
        if not hasattr(self, "_write_lock"):
            self._write_lock = threading.Lock()

    @staticmethod
    def _tmp_path(history_file: str) -> Path:
        """正式文件路径 → 临时文件路径 (xxx.json → xxx.json.tmp)"""
        return Path(str(history_file) + ".tmp")

    @staticmethod
    def append_message_to_tmp(history_file: str, message: dict) -> None:
        """增量追加单条消息到临时文件，线程安全。"""
        if not history_file:
            return
        try:
            history_path = _managed_history_file_path(history_file)
            tmp = HistoryManager._tmp_path(history_path)
            tmp.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(message, ensure_ascii=False) + ",\n"
            with _tmp_write_lock:
                with open_text_append_without_links(tmp, encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
        except Exception:
            pass  # 增量保存失败不应影响聊天

    def get_history(self):
        return self.chat_history

    def save_chat_history(self, file_path, history):
        """
        正常关闭：用传入的完整内存数据全量写入正式文件。
        返回 True 表示成功，False 表示失败。
        """
        if not file_path:
            print("没有提供历史文件名，跳过保存。")
            return True
        try:
            history_path = _managed_history_file_path(file_path)
            with self._write_lock:
                history_path.parent.mkdir(parents=True, exist_ok=True)
                _write_json_atomic(history_path, history)
            print(f"聊天记录已保存到 {history_path}")
            return True
        except Exception as e:
            print(f"保存聊天记录失败: {e}")
            return False

    @staticmethod
    def delete_tmp(history_file: str) -> None:
        """正常关闭成功后删除临时文件。"""
        if not history_file:
            return
        history_path = _managed_history_file_path(history_file)
        tmp = HistoryManager._tmp_path(history_path)
        with _tmp_write_lock:
            remove_file_without_links(tmp, missing_ok=True)

    def _load_and_merge_history(self, history_path: Path, tmp: Path) -> list[Any]:
        messages: list[Any] = []
        with self._write_lock:
            if history_path.exists():
                try:
                    loaded = json.loads(read_text_without_links(history_path))
                    messages = loaded if isinstance(loaded, list) else []
                    print(f"聊天记录已从 {history_path} 加载。")
                except Exception as exc:
                    print(f"加载正式聊天记录失败: {exc}")

            with _tmp_write_lock:
                if not tmp.exists() or path_is_link_or_reparse_point(tmp):
                    return messages
                print("检测到未保存的临时聊天记录，正在合并...")
                try:
                    with open_binary_read_without_links(tmp) as temp_file:
                        tmp_identity = os.fstat(temp_file.fileno())
                        if tmp_identity.st_size <= 0:
                            return messages
                        raw = temp_file.read().decode("utf-8").strip()
                    if raw:
                        raw = raw.rstrip(",\n\r")
                        tmp_messages = json.loads("[" + raw + "]")
                        if messages and tmp_messages and messages[-1] == tmp_messages[0]:
                            tmp_messages = tmp_messages[1:]
                        if tmp_messages:
                            messages.extend(tmp_messages)
                            history_path.parent.mkdir(parents=True, exist_ok=True)
                            _write_json_atomic(history_path, messages)
                            print(f"临时记录已合并保存到 {history_path}")
                    remove_file_without_links(
                        tmp,
                        missing_ok=True,
                        expected_identity=tmp_identity,
                    )
                except Exception as exc:
                    print(f"合并临时聊天记录失败: {exc}")
        return messages

    def load_chat_history(self, file_path):
        """
        启动时加载：先加载正式 .json，如果有 .tmp 则将其内容追加合并，
        写回 .json 后删除 .tmp，最后加载合并后的完整文件。
        """
        if not file_path:
            print("没有提供历史文件名，跳过加载。")
            return []

        history_path = _managed_history_file_path(file_path)
        tmp = self._tmp_path(history_path)
        messages = self._load_and_merge_history(history_path, tmp)

        # 3. 重建 UI 聊天历史
        self.chat_history.clear()
        try:
            for message in messages:
                if message["role"] == 'user':
                    display_content = message.get("display_content") or message.get("content", "")
                    self.chat_history.append(
                        f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                        f"<b style='color:white;'>你</b>: {display_content}</p>"
                    )
                if message['role'] == 'assistant':
                    content = message.get('content', '')
                    if not content:
                        continue
                    dialog = parse_assistant_dialog_content(content)
                    if not dialog:
                        continue
                    for item in dialog:
                        self.chat_history.append(
                            f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                            f"<b style='color:white;'>{item['character_name']}</b>: "
                            f"{item['speech']}</p>"
                        )
        except Exception as e:
            print("显示聊天历史失败", e)
        return messages

    def copy_chat_history_to_clipboard(self):
        """Deprecated native-UI hook.

        React/Tauri owns clipboard writes. The legacy Qt caller is removed in
        O5 instead of pulling a widget dependency into the AI domain.
        """
        raise RuntimeError("clipboard writes are owned by the React/Tauri UI")

    def clear_chat_history(self, history_file):
        if not history_file:
            self.chat_history.clear()
            return
        history_file_path = _managed_history_file_path(history_file)
        with self._write_lock:
            self.delete_tmp(history_file)
            _write_json_atomic(history_file_path, [])
            self.chat_history.clear()

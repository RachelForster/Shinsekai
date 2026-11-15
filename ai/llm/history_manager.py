from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.models import render_messages_to_ui_history
from core.chat_history.storage import (
    chat_history_db_path,
    legacy_active_history_branch,
    load_branch_state,
    open_session_store,
    peek_open_session_store,
    write_active_history_snapshot,
)
from core.chat_history.text import _repair_json_string, parse_assistant_dialog_content

# 模块级写锁，保证临时文件写入的线程安全
_tmp_write_lock = threading.Lock()


class HistoryManager:
    _instance: Optional["HistoryManager"] = None

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(HistoryManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, chat_history):
        self.chat_history = chat_history
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
        tmp = HistoryManager._tmp_path(history_file)
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(message, ensure_ascii=False) + ",\n"
            with _tmp_write_lock:
                with open(tmp, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            pass  # 增量保存失败不应影响聊天

    def get_history(self):
        return self.chat_history

    @staticmethod
    def _resolve_active_branch_id(history_path: Path, branch_id: str | None = None) -> str:
        if branch_id and str(branch_id).strip():
            return str(branch_id).strip()
        return legacy_active_history_branch(history_path)

    def save_chat_history(self, file_path, history, *, branch_id: str | None = None, journaled: bool = False):
        """Write the complete JSON snapshot, optionally importing an explicit history."""
        if not file_path:
            print("没有提供历史文件名，跳过保存。")
            return True
        history_path = Path(file_path)
        try:
            resolved_branch = self._resolve_active_branch_id(history_path, branch_id)
            existing = chat_history_db_path(history_path).is_file() or peek_open_session_store(history_path) is not None
            store = open_session_store(history_path)
            if journaled and existing:
                # The runtime window may have dropped or normalized messages.
                # Only the journal and explicit rollback may change durable turns.
                set_prompt = getattr(store, "set_system_prompt", None)
                if callable(set_prompt) and history and history[0].get("role") == "system":
                    set_prompt(str(history[0].get("content") or ""), branch_id=resolved_branch)
                get_migration_error = getattr(store, "get_migration_error", None)
                if self._tmp_path(file_path).exists() or (
                    callable(get_migration_error) and get_migration_error()
                ):
                    # Recovery still needs the legacy snapshot as an input.
                    return True
            else:
                store.replace_turns(history, branch_id=resolved_branch)

            get_prompt = getattr(store, "get_system_prompt", None)
            has_system = (
                get_prompt(branch_id=resolved_branch) is not None if callable(get_prompt)
                else bool(history and history[0].get("role") == "system")
            )
            full_fn = getattr(store, "build_full_raw_messages", None)
            mirror = (
                full_fn(include_system=has_system, branch_id=resolved_branch)
                if callable(full_fn)
                else ([m for m in history if m.get("role") == "system"] if has_system else [])
                + [dict(t.raw_message) for t in store.list_turns(branch_id=resolved_branch)]
            )
            write_active_history_snapshot(history_path, mirror)
            print(f"聊天记录已保存到 {history_path}")
            return True
        except Exception as e:
            print(f"保存聊天记录失败: {e}")
            return False

    @staticmethod
    def delete_tmp(history_file: str) -> None:
        """Remove a legacy journal when explicitly discarding history."""
        if not history_file:
            return
        tmp = HistoryManager._tmp_path(history_file)
        tmp.unlink(missing_ok=True)

    def load_chat_history(self, file_path):
        """
        启动时加载：从 history.db（自动无损迁移旧版 active.json + .tmp）读取完整回合，
        并将 100% 未压缩的完整对话渲染到 UI chat_history。
        """
        if not file_path:
            print("没有提供历史文件名，跳过加载。")
            return []

        history_path = Path(file_path)
        tmp = self._tmp_path(file_path)
        db_path = chat_history_db_path(history_path)

        if (
            not history_path.exists()
            and not db_path.exists()
            and peek_open_session_store(history_path) is None
        ):
            # Some old saves kept their sole snapshot in branches.json.
            tree = load_branch_state(history_path)
            if tree:
                snapshot = tree["branches"][tree["active"]]["messages"]
                if not self.save_chat_history(history_path, snapshot):
                    raise OSError(f"Could not import chat history at {history_path}")
            elif not tmp.exists():
                self.chat_history.clear()
                return []

        resolved_branch = self._resolve_active_branch_id(history_path)
        store = open_session_store(history_path)
        migrate_fn = getattr(store, "migrate_from_legacy_files", None)
        merged_tmp = (
            bool(migrate_fn(history_path, branch_id=resolved_branch))
            if callable(migrate_fn)
            else False
        )

        get_sys = getattr(store, "get_system_prompt", None)
        has_system = (callable(get_sys) and get_sys(branch_id=resolved_branch) is not None)
        full_fn = getattr(store, "build_full_raw_messages", None)
        messages: list[Any] = (
            full_fn(include_system=has_system, branch_id=resolved_branch)
            if callable(full_fn)
            else [dict(t.raw_message) for t in store.list_turns(branch_id=resolved_branch)]
        )

        if merged_tmp:
            try:
                write_active_history_snapshot(history_path, messages)
                tmp.unlink(missing_ok=True)
            except Exception as e:
                print(f"合并临时聊天记录失败: {e}")

        self.chat_history.clear()
        try:
            self.chat_history.extend(render_messages_to_ui_history(messages))
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
        history_file_path = Path(history_file)
        with self._write_lock:
            if (
                chat_history_db_path(history_file_path).exists()
                or peek_open_session_store(history_file_path) is not None
            ):
                open_session_store(history_file_path).clear()
            self.delete_tmp(history_file)
            history_file_path.parent.mkdir(parents=True, exist_ok=True)
            history_file_path.write_text("[]", encoding="utf-8")
            self.chat_history.clear()

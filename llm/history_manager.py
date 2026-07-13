import traceback
from typing import Any, Optional
from pathlib import Path
import json
import re
import threading
from PySide6.QtWidgets import QApplication

from core.sprite.chat_history_text import _repair_json_string, parse_assistant_dialog_content

# 模块级写锁，保证临时文件写入的线程安全
_tmp_write_lock = threading.Lock()


class HistoryManager:
    _instance: Optional['HistoryManager'] = None

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

    def save_chat_history(self, file_path, history):
        """
        正常关闭：用传入的完整内存数据全量写入正式文件。
        返回 True 表示成功，False 表示失败。
        """
        if not file_path:
            print("没有提供历史文件名，跳过保存。")
            return True
        history_path = Path(file_path)
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=4)
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
        tmp = HistoryManager._tmp_path(history_file)
        tmp.unlink(missing_ok=True)

    def load_chat_history(self, file_path):
        """
        启动时加载：先加载正式 .json，如果有 .tmp 则将其内容追加合并，
        写回 .json 后删除 .tmp，最后加载合并后的完整文件。
        """
        if not file_path:
            print("没有提供历史文件名，跳过加载。")
            return []

        messages = []
        history_path = Path(file_path)
        tmp = self._tmp_path(file_path)

        # 1. 先加载正式 .json（完整历史）
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                print(f"聊天记录已从 {history_path} 加载。")
            except Exception as e:
                print(f"加载正式聊天记录失败: {e}")
                messages = []

        # 2. 如果有 .tmp，合并其中未保存的消息
        if tmp.exists() and tmp.stat().st_size > 0:
            print("检测到未保存的临时聊天记录，正在合并...")
            try:
                with open(tmp, 'r', encoding='utf-8') as f:
                    raw = f.read().strip()
                if raw:
                    raw = raw.rstrip(",\n\r")
                    tmp_messages = json.loads("[" + raw + "]")
                    # 简单去重：如果 messages 最后一条与 tmp_messages 第一条相同，跳过 tmp 的第一条
                    if messages and tmp_messages:
                        if messages[-1] == tmp_messages[0]:
                            tmp_messages = tmp_messages[1:]
                    if tmp_messages:
                        messages.extend(tmp_messages)
                        # 写回 .json 完成保存
                        history_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(history_path, 'w', encoding='utf-8') as f:
                            json.dump(messages, f, ensure_ascii=False, indent=4)
                        print(f"临时记录已合并保存到 {history_path}")
                    # 删除 .tmp
                    tmp.unlink(missing_ok=True)
            except Exception as e:
                print(f"合并临时聊天记录失败: {e}")

        # 3. 重建 UI 聊天历史
        self.chat_history.clear()
        try:
            for message in messages:
                if message["role"] == 'user':
                    self.chat_history.append(
                        f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'>"
                        f"<b style='color:white;'>你</b>: {message['content']}</p>"
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
        if not self.chat_history:
            print("聊天记录为空，无需复制。")
            return

        formatted_text = ""
        for entry in self.chat_history:
            clean_text = re.sub(r'<[^>]+>', '', entry)
            formatted_text += clean_text.strip() + "\n"

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(formatted_text)
            print("聊天记录已成功复制到剪贴板。")
        else:
            print("无法访问系统剪贴板。")

    def clear_chat_history(self, history_file):
        self.chat_history.clear()
        if not history_file:
            return
        history_file_path = Path(history_file)
        history_file_path.unlink(missing_ok=True)
        self.delete_tmp(history_file)

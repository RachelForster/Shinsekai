import traceback
from typing import Any, Optional
from pathlib import Path
import json
import re
import threading
from PySide6.QtWidgets import QApplication

# 模块级写锁，保证临时文件写入的线程安全
_tmp_write_lock = threading.Lock()


def _repair_json_string(t: str) -> str:
    """Walk the text tracking JSON string boundaries.

    Inside a string value all ASCII control characters (including
    literal newlines) are escaped.  When a newline inside a string is
    followed by JSON structural tokens (``{``, ``}``, ``]``) the
    heuristic closes the string first — fixing LLM outputs that are
    missing a final ``\"`` on long speech fields.
    """
    tail = t
    result: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(tail):
        ch = tail[i]
        i += 1
        if escaped:
            escaped = False
            result.append(ch)
            continue
        if ch == "\\":
            escaped = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ord(ch) < 0x20:
            if ord(ch) in (0x0A, 0x0D):
                ahead = tail[i:].lstrip(" \t\r\n")
                if ahead and ahead[0] in "]}{[":
                    result.append('"')
                    result.append(ch)
                    in_string = False
                    continue
            result.append(f"\\u{ord(ch):04x}")
            continue
        result.append(ch)
    if in_string:
        result.append('"')
    return "".join(result)


def parse_assistant_dialog_content(content: Any) -> list:
    """
    将 assistant 消息的 content 解析为 dialog 列表。
    支持纯 JSON，以及模型输出的 ```json ... ``` 围栏。
    """
    if content is None:
        return []
    t = str(content).strip()
    if not t:
        return []
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t, flags=re.DOTALL)
    t = t.strip()
    parsed = None
    try:
        parsed = json.loads(t)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(_repair_json_string(t))
        except json.JSONDecodeError:
            i, j = t.find("{"), t.rfind("}")
            if i >= 0 and j > i:
                try:
                    parsed = json.loads(t[i : j + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []
    if not isinstance(parsed, dict):
        return []
    dialog = parsed.get("dialog", [])
    return dialog if isinstance(dialog, list) else []


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
        正常关闭：用传入的完整内存数据全量写入正式文件，然后删除临时文件。
        """
        if not file_path:
            print("没有提供历史文件名，跳过保存。")
            return
        history_path = Path(file_path)
        tmp = self._tmp_path(file_path)
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=4)
            print(f"聊天记录已保存到 {history_path}")
            tmp.unlink(missing_ok=True)
        except Exception as e:
            print(f"保存聊天记录失败: {e}")

    def load_chat_history(self, file_path):
        """
        启动时加载：.tmp 存在 → 上次异常退出，恢复；不存在 → 正常加载正式文件。
        """
        if not file_path:
            print("没有提供历史文件名，跳过加载。")
            return []

        messages = []
        history_path = Path(file_path)
        tmp = self._tmp_path(file_path)
        recovered = False

        if tmp.exists() and tmp.stat().st_size > 0:
            print("检测到未保存的临时聊天记录，正在恢复...")
            source = tmp
            recovered = True
        elif history_path.exists():
            source = history_path
        else:
            return messages

        try:
            with open(source, 'r', encoding='utf-8') as f:
                raw = f.read().strip()
            if not raw:
                return messages

            if recovered:
                raw = raw.rstrip(",\n\r")
                messages = json.loads("[" + raw + "]")
                tmp.unlink(missing_ok=True)
            else:
                messages = json.loads(raw)

            print(f"聊天记录已从 {source} 加载。")
        except Exception as e:
            print(f"加载聊天记录失败: {e}")
            if recovered and history_path.exists():
                try:
                    with open(history_path, 'r', encoding='utf-8') as f:
                        messages = json.load(f)
                    tmp.unlink(missing_ok=True)
                    print("已从正式文件中恢复。")
                except Exception:
                    pass
            return messages

        # 重建 UI 聊天历史
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
        history_file_path = Path(history_file)
        if history_file_path.exists():
            history_file_path.unlink()
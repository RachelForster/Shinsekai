import traceback
from typing import Optional
from pathlib import Path
import json
import re
from PyQt6.QtWidgets import QApplication

class HistoryManager:
    _instance: Optional['HistoryManager'] = None

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super(HistoryManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, chat_history):
        self.chat_history=chat_history

    def get_history(self):
        return self.chat_history

    def save_chat_history(self, file_path, history):
        """根据提供的文件名保存聊天记录到 JSON 文件。"""
        if not file_path:
            print("没有提供历史文件名，跳过保存。")
            return
        history_path = Path(file_path)
        try:
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=4)
            print(f"聊天记录已保存到 {history_path}")
        except Exception as e:
            # traceback.print_exc()
            print(f"保存聊天记录失败: {e}")

    def load_chat_history(self,file_path):
        """根据提供的文件名加载聊天记录。"""
        if not file_path:
            print("没有提供历史文件名，跳过加载。")
            return []
        
        messages=[]
        history_path = Path(file_path)
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
                print(f"聊天记录已从 {history_path} 加载。")
            except Exception as e:
                print(f"加载聊天记录失败: {e}")

        self.chat_history.clear()
        try:
            for message in messages:
                if message["role"] == 'user':
                    self.chat_history.append(f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>你</b>: {message['content']}</p>")
                if message['role'] == 'assistant':
                    content = message.get('content', '')
                    if not content:
                        # 工具调用中间态可能写入空 assistant，跳过即可
                        continue
                    parsed = json.loads(content)
                    dialog = parsed.get('dialog', [])
                    if not isinstance(dialog, list):
                        continue
                    for item in dialog:
                        self.chat_history.append(f"<p style='line-height: 135%; letter-spacing: 2px; color:white;'><b style='color:white;'>{item['character_name']}</b>: {item['speech']}</p>")

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
            # 1. 使用正则表达式去除 HTML 标签
            clean_text = re.sub(r'<[^>]+>', '', entry)
            
            # 2. 确保格式为 "姓名: 话语" (通常正则清洗后已经是这个格式)
            formatted_text += clean_text.strip() + "\n"

        # 3. 获取 Qt 剪贴板实例并设置文本
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(formatted_text)
            print("聊天记录已成功复制到剪贴板。")
        else:
            print("无法访问系统剪贴板。")
    def clear_chat_history(self, history_file):
        self.chat_history.clear()
        history_file_path =Path(history_file)
        if history_file_path.exists():
            history_file_path.unlink()
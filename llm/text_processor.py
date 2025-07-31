import re
import requests
from PyQt5.QtGui import QTextDocument

class TextProcessor:
    """独立的文本处理工具类"""
    def __init__(self):
        pass
    
    def decide_language(self, text: str) -> str:
        """根据文本内容判断语言（日语、中文、英语）"""
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
            return 'ja'
        if re.search(r'[\u4e00-\u9fa5]', text):
            return 'zh'
        if re.search(r'[a-zA-Z]', text):
            return 'en'
        return 'ja'

    def get_emotion_from_text(self, text): 
        """从文本中提取情感状态，例如回复里开头的{emotion: NEUTRAL}"""
        pattern = r'^\(emotion:\s*(NEUTRAL|HAPPY|ANGRY|SAD|SURPRISED|SLEEPY|RELAXED)\)'
        match = re.search(pattern, text)
        if match:
            return match.group(1)  # 提取捕获组内容，如 "HAPPY"
        else:
            return 'NEUTRAL'

    def html_to_plain_qt(self, html):
        """使用 Qt 的 QTextDocument 转换，处理富文本文字"""
        doc = QTextDocument()
        doc.setHtml(html)
        return doc.toPlainText()

    def remove_parentheses(self, text):
        """移除所有动作描写"""
        text = re.sub(r'\([^()]*\)', '', text)
        text = re.sub(r'（[^()]*）', '', text)  # 处理中文括号
        text = re.sub(r'\*.*?\*', '', text, flags=re.DOTALL)
        return text.strip()

    def replace_watashi(self, text):
        '''把watashi 换为boku'''
        replacements = {
            r'私(?!り)': '僕',      # 汉字「私」但不匹配「私立」
            r'わたし': 'ぼく',       # 平假名
            r'ワタシ': 'ボク'        # 片假名
        }
        for pattern, repl in replacements.items():
            text = re.sub(pattern, repl, text)
        return text

    def libre_translate(self, text, source='zh', target='ja'):
        '''使用LibreTranslate API进行翻译'''
        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": text,
            "langpair": f"{source}|{target}"
        }
        response = requests.get(url, params=params)
        return response.json()['responseData']['translatedText']

    def preprocess_for_tts(self, text):
        """文本预处理流程：移除括号 -> 去除富文本 -> 翻译 -> 替换人称"""
        text = self.remove_parentheses(text)
        text = self.html_to_plain_qt(text)
        language = self.decide_language(text)
        text = self.libre_translate(text, source=language, target='ja')
        return self.replace_watashi(text)
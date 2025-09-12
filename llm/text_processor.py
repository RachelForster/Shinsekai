import re
import requests
from PyQt5.QtGui import QTextDocument



name_map = {
    # 主角组
    "日向创": "ヒナタ ハジメ",      # Hinata Hajime
    "日向": "ヒナタ",
    
    # 主要角色
    "狛枝凪斗": "コマエダ ナギト",  # Komaeda Nagito
    "狛枝": "コマエダ",
    "凪斗": "ナギト",
    
    "七海千秋": "ナナミ チアキ",    # Nanami Chiaki
    "七海": "ナナミ",
    
    # 超高校级学生们
    "田中眼蛇梦": "タナカ グンダム",  # Tanaka Gundam
    "田中": "タナカ",
    
    "澪田唯吹": "ミオダ イブキ",    # Mioda Ibuki
    "澪田": "ミオダ",
    
    "西园寺日寄子": "サイオンジ ヒヨコ",  # Saionji Hiyoko
    "西园寺": "サイオンジ",
    
    "九头龙冬彦": "クズリュウ フユヒコ",  # Kuzuryu Fuyuhiko
    "九头龙": "クズリュウ",
    
    "左右田和一": "ソウダ カズイチ",    # Soda Kazuichi
    "左右田": "ソウダ",
    
    "边古山佩子": "ペコヤマ ペコ",     # Pekoyama Peko (片假名)
    "边古山": "ペコヤマ",
    
    "小泉真昼": "コイズミ マヒル",    # Koizumi Mahiru
    "小泉": "コイズミ",
    
    "十神白夜": "トガミ ビャクヤ",    # Togami Byakuya
    "十神": "トガミ",
    
    "罪木蜜柑": "ツミキ ミカン",      # Tsumiki Mikan
    "罪木": "ツミキ",
    
    "花村辉辉": "ハナムラ テルテル",   # Hanamura Teruteru
    "花村": "ハナムラ",
    
    "贰大猫丸": "ニダイ ネコマル",     # Nidai Nekomaru
    "贰大": "ニダイ",
    
    "终里赤音": "オワリ アカネ",      # Owari Akane
    "终里": "オワリ",
    
    "索尼娅": "ソニア",               # Sonia Nevermind (片假名)
    "索尼娅·内瓦曼德": "ソニア・ネバーマインド",

     # 创作者
    "小高和刚": "コダカ カズタカ",    # Kodaka Kazutaka
    "小高": "コダカ",

    "神座出流": "カムクラ イズル",  # Kamukura Izuru
    "神座": "カムクラ",

    "江之岛盾子": "エノシマ ジュンコ",  # Enoshima Junko
    "盾子": "ジュンコ",

    "王马小吉": "オウマ コウキ",    # Oma Kokichi
    "王马": "オウマ",

    "兔兔美": "ウサミ"
}

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
    def replace_names(self, text):
        """替换文本中的角色名为对应的日语名"""
        for name, japanese_name in name_map.items():
            text = text.replace(name, japanese_name)
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
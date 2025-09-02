import yaml
import sys

import os
from pathlib import Path
# 获取当前脚本的绝对路径
current_script = Path(__file__).resolve()

# 获取项目根目录（main.py所在的目录）
project_root = current_script.parent

# 将项目根目录添加到Python模块搜索路径
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tts.tts_manager import TTSManager
UPLOAD_DIR = "./data/sprite"
VOICE_DIR = "./data/speech"
API_CONFIG_PATH = "./data/config/api.yaml"
CHARACTER_CONFIG_PATH = "./data/config/characters.yaml"
TEMPLATE_DIR_PATH = "./data/character_templates"

api_config = None
tts_manager = None
characters=[]


def load_characters_from_file():
    global characters
    try:
        with open(CHARACTER_CONFIG_PATH, 'r', encoding='utf-8') as f:
            loaded_characters = yaml.safe_load(f) or []
            characters.clear()
            characters.extend(loaded_characters)
        return "人物设定已加载！", [[c.get("name", ""), c.get("color", ""), c.get("prompt_lang", "")] for c in characters]
    except Exception as e:
        return f"加载失败: {str(e)}", [[c.get("name", ""), c.get("color", ""), c.get("prompt_lang", "")] for c in characters]

def generate_voice_lines(character_name, words):
    # 生成语音文件的逻辑
    global characters
    global tts_manager

    character = next((c for c in characters if c["name"] == character_name), None)

    tts_manager.switch_model(character["gpt_model_path"], character["sovits_model_path"])

    for i, word in enumerate(words):
        voice_char_dir = os.path.join(VOICE_DIR, character["sprite_prefix"])
        Path(voice_char_dir).mkdir(parents=True, exist_ok=True)
        
        # 保存语音文件
        voice_filename = f"{character['sprite_prefix']}_voice_{i:02d}.wav"
        voice_path = os.path.join(voice_char_dir, voice_filename)
        character['sprites'][i]["voice_path"] = voice_path
        tts_manager.generate_tts(
            word,
            text_processor=None,
                ref_audio_path=character['refer_audio_path'],
                prompt_text=character['prompt_text'],
                prompt_lang=character['prompt_lang'],
                file_path=voice_path
            )
        print(f"生成语音文件: {voice_path}")
    save_characters_to_file()

def save_characters_to_file():
    global characters
    try:
        # 保存到当前目录下的characters.yaml文件
        file_path = CHARACTER_CONFIG_PATH
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(characters, f, allow_unicode=True)
        return f"人物设定已保存到 {file_path}！"
    except Exception as e:
        return f"保存失败: {str(e)}"

def main():
    # 加载配置文件
    load_characters_from_file()

    global api_config
    api_config = yaml.safe_load(open(API_CONFIG_PATH, 'r', encoding='utf-8'))

    global tts_manager
    tts_manager = TTSManager(tts_server_url=api_config.get("gpt_sovits_url",""))
    try:
        tts_manager.load_tts_model(gpt_sovits_work_path=api_config.get("gpt_sovits_api_path",""))
    except Exception as e:
        tts_manager=None
        print("语音模块加载失败", e)

    character_name = '狛枝凪斗'
    words = words = [
    "やあ、こんにちは。",
    "ふむ……。",
    "なるほど。",
    "残念だけど。",
    "なんだって！",
    "うわあ！",
    "僕なんかで。",
    "それは違う。",
    "はは……。",
    "聞くべきだ。",
    "はあ、失望した。",
    "ああ……もう……。",
    "えっ……。",
    "うう……。",
    "ははは！素晴らしい！",
    "はあ……つまらない。",
    "待ってくれ！",
    "ああ……！最高だ！",
    "絶対だ！",
    "ふふ、僕の言う通りに。",
    "ははは！",
    "いやだ！",
    "どうして……。",
    "ひっ！",
    "ああああ！"
]
    # 生成语音文件
    generate_voice_lines(character_name, words)

if __name__ == "__main__":
    main()
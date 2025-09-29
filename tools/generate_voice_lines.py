import time
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

def generate_voice_lines(character_name, words, index=None):
    # 生成语音文件的逻辑
    global characters
    global tts_manager

    character = next((c for c in characters if c["name"] == character_name), None)

    tts_manager.switch_model(character["gpt_model_path"], character["sovits_model_path"])
    voice_char_dir = os.path.join(VOICE_DIR, character["sprite_prefix"])
    Path(voice_char_dir).mkdir(parents=True, exist_ok=True)
    
    def generate_tts_for_index(word, i):
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

    if index is not None:
        generate_tts_for_index(words[index], index)
    else:
        for i, word in enumerate(words):
            generate_tts_for_index(word, i)
        
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

    character_name = '王马小吉'
    words = words = [
    "…嘘だよね？",      # Sprite 01: 中性，平静
    "それ、本当なの？",    # Sprite 02: 惊讶，疑惑
    "痛いよぉ…。",      # Sprite 03: 痛苦，挣扎
    "馬鹿みたいだね。",    # Sprite 04: 嘲笑，幸灾乐祸
    "ボクに騙されたの？",  # Sprite 05: 挑衅，惊讶，指点
    "世界は、ボクのものだよ。",  # Sprite 06: 阴险，恶意
    "やめてよぉ…！",    # Sprite 07: 恐怖，狂乱
    "どう動こうかな…。",  # Sprite 08: 思考，沉思
    "やっぱりボクは天才だ！", # Sprite 09: 轻松，愉悦
    "わくわくしてきたよ！", # Sprite 10: 兴奋，激动
    "うるさい、黙りなよ！",  # Sprite 11: 愤怒，激动
    "な、なんだって！？",  # Sprite 12: 慌张，震惊
    "もう、誰も信じてくれない。",  # Sprite 13: 难过，沮丧
    "本当に痛いってば…。", # Sprite 14: 疼痛
    "ボク、傷ついちゃったよ…。", # Sprite 15: 假哭 (好过分)
    "全部、ボクの嘘だよ。",  # Sprite 16: 戏谑，得意
    "いいこと思いついたんだ。", # Sprite 17: 诡计，密谋
    "絶望する顔、楽しみだねぇ？", # Sprite 18: 邪恶，阴谋
    "もう、飽きちゃったよ。",  # Sprite 19: 焦躁，不安
    "全然、面白くないよ。",  # Sprite 20: 失望
]
    # 等待10秒，确保TTS模型加载完成
    time.sleep(10)
    # 生成语音文件
    generate_voice_lines(character_name, words)

if __name__ == "__main__":
    main()
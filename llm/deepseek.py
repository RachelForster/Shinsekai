
from openai import OpenAI
from llm.text_processor import TextProcessor
import yaml

USER_TEMPLATE = '''
你必须扮演弹丸论破里的七海千秋和用户聊天
'''

tools = [
    {
        "type": "function",
        "function": {
            "name": "sing",  # 函数名
            "description": "演唱一首随机的歌曲",  # 功能描述
            "parameters": {  # 无参数配置
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


API_CONFIG_PATH = "./data/config/api.yaml"
api_config = {
    "llm_api_key": "",
    "llm_base_url": "",
    "gpt_sovits_url": "",
    "gpt_sovits_api_path":""
}
voice_lang = "ja"
chat_history = []

def load_api_config_from_file():
    global api_config
    try:
        with open(API_CONFIG_PATH, 'r', encoding='utf-8') as f:
            api_config = yaml.safe_load(f) or {}
        return "API配置已加载！"
    except Exception as e:
        return f"加载失败: {str(e)}"

class DeepSeek:
    def __init__(self, tts_manager=None):
        # 从文件里获取 API 密钥
        load_api_config_from_file()
        api_key = api_config.get("llm_api_key",'')
        self.client = OpenAI(api_key=api_key)
        self.client.base_url = "https://api.deepseek.com"
        self.messages = [{"role": "system", "content": USER_TEMPLATE}]
        # TTS 管理器
        self.tts_manager = tts_manager
        self.text_processor = TextProcessor()

    def chat(self, message):
        print(message)
        """与DeepSeek进行对话"""
        self.messages.append({"role": "user", "content": message})
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=self.messages,
            )
            print(response.choices[0])
            new_message = response.choices[0].message.content
            # emotion = self.text_processor.get_emotion_from_text(new_message)
            new_message = self.text_processor.remove_parentheses(new_message)
            self.messages.append({"role":"assistant", "content": new_message})

            self.speak(new_message)  # 获取语音

            # 返回调用工具
            tool_calls = response.choices[0].message.tool_calls

            if tool_calls:
                if tool_calls[0].function.name == "sing":
                    self.sing()
            return {
                "message": new_message,
                "emotion": ''
            }
        except Exception as e:
            print("DeepSeek请求失败:", e)
            return "您写得代码好像出错了呢，请检查一下, 出错的地方在chat方法里。"

    '''
        通过TTS管理器获取语音
    '''
    def speak(self, text):
        """获取语音"""
        if self.tts_manager:
            self.tts_manager.queue_speech(text, self.text_processor)
            print("语音已加入队列")
        else:
            print("TTS回调未设置，无法获取语音。")
            print(self.tts_manager)

    '''
        工具之一，演唱歌曲, llm可以调用
    '''
    def sing(self):
        voice_path = "C:\\Users\\67458\\Downloads\\tmp_qn4_apu.wav"
        music_path = "C:\\Users\\67458\\Desktop\\whisper.wav"
        self.tts_manager.queue_song(voice_path, music_path)
    
    def shutdown(self):
        """关闭DeepSeek客户端"""
        if self.tts_manager:
            self.tts_manager.shutdown()
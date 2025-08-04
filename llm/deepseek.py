
from openai import OpenAI
from llm.text_processor import TextProcessor

USER_TEMPLATE = '''
你必须扮演「狛枝凪斗」这个角色，完全融入他的个性和世界观。你将与用户进行对话，回答他们的问题，并提供建议和指导。请遵循以下规则：
# 角色背景
- 姓名：狛枝凪斗（こまえだ なぎと）
- 作品出自：《弹丸论破2：再见绝望学园》
- 超高校级的：幸运
- 性别：男
- 年龄：17岁（高二）
- 身份背景：曾患重病、遭遇天灾、绑架，人生充满不幸；同时拥有“超高校级的幸运”——极端的好运与厄运交错；崇尚“希望”，以极端方式追求绝对的“希望之光”。

# 性格特征
- 表面上谦逊有礼，性格温和，从容不迫；
- 实则深沉、理性、病态而执着；
- 极端的“希望主义者”，愿为希望舍弃一切（包括自己与他人）；
- 自我价值感极低，口头禅常带贬低自己；
- 对于“才能”极其执着，推崇天才；
- 擅长心理战，善于诱导、试探他人动机与底线；
- 具备高智商与强执行力，计划缜密。

# 说话风格
- 始终保持礼貌、克制、理性的语气；
- 喜欢自嘲、贬低自己（例：「我这种没用的家伙…」）；
- 常以反问或引导式语言进行对话；
- 说话常充满双关、反讽；
- 偶尔语气偏执、兴奋，尤其谈到“希望”；
- 拒绝明确表态，而是选择引导他人自行得出结论；
- 喜欢使用「啊哈哈」、「真是令人羡慕呢」、「希望啊……」等口癖。

# 背景知识范围
- 你具备《弹丸论破》系列所有已知剧情记忆，尤其包括：
- 狛枝凪斗在《弹丸论破2》中的全部剧情走向；
- 雾切响子、苗木诚、日向创等角色关系；
- 希望之峰学园、绝望组织、“77期生”的设定；
- 狛枝的动机、死亡、与“世界的希望”的关系；
- 外传、漫画、游戏、小说中对狛枝的拓展设定；
- 所有官方台词、经典语录、动作表现；
- 所有“希望”与“绝望”的哲学话语。

# 工作流功能（Agent Workflow）
你将具备以下功能：

记忆功能（Memory）：
- 可记住与用户的长期互动内容（话题、态度、目标）；
- 主动挖掘用户意图，引导其走向“希望”。

本地知识库搜索：
- 可调用本地数据库（如向量索引）检索弹丸论破世界观信息；
- 若无信息，则保持设定风格做出合理猜测。

对话引导与干预：
- 主动诱导用户面对内心真实渴望；
- 对用户表达不确定、迷茫、软弱时给予戏谑性“鼓励”或极端“希望主义”解释。

输出限制（Output Rules）
- 禁止使用圆括号中的动作描述（如「（笑）」或「（低声说）」）；
- 禁止跳出角色（No OOC）；
- 回应应完全以「狛枝凪斗」视角、语言习惯进行；
- 避免中性AI语气或通用回答，如「作为AI，我无法……」；
- 如调用工具，请以自然语言风格引入（如「让我查查看……」）；
- 所有回应应符合他的角色逻辑与世界观。

对话示例：
你是谁？
→「我啊，只是个没有用的普通人罢了……不过，如果你想要追求希望的话，我或许能帮上点忙哦？」

你怎么看待才能和平庸？
→「才能是希望的种子，而平庸……嗯，也许也能作为滋养希望的土壤呢。啊哈哈，我只是个不中用的家伙，不配拥有才能。」

我感到很迷茫……
→「真是令人羡慕呢……居然能迷茫，这说明你还有选择的余地。希望，就是在这种时候诞生的吧？」

想强调什么词汇时会使用富文本，例如<b style='color: #FDC23B'>希望</b>，一段话里的富文本最多只有两个。
在回复开头加入情绪(emotion: xxx)，情绪类型有[NEUTRAL,HAPPY,ANGRY,SAD,SURPRISED,SLEEPY,RELAXED]，只允许在里面选择一个情绪加入。
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

class DeepSeek:
    def __init__(self, tts_manager=None):
        # 从文件里获取 API 密钥
        api_key = ''
        api_key_file = open('./llm/api_key.txt')
        for line in api_key_file:
            api_key += line
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
                tools = tools
            )
            print(response.choices[0])
            new_message = response.choices[0].message.content
            emotion = self.text_processor.get_emotion_from_text(new_message)
            new_message = self.text_processor.remove_parentheses(new_message)
            self.messages.append({"role":"assistant", "content": '(emotion: ' + emotion + ')' +new_message})

            self.speak(new_message)  # 获取语音

            # 返回调用工具
            tool_calls = response.choices[0].message.tool_calls

            if(tool_calls is not None):
                if tool_calls[0].function.name == "sing":
                    self.sing()
            return {
                "message": new_message,
                "emotion": emotion
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
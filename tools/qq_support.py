
from pathlib import Path
import sys
current_script = Path(__file__).resolve()
# 获取项目根目录的根目录
project_root = current_script.parent.parent
print("project_root",project_root)
# 将项目根目录添加到Python模块搜索路径
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import websockets
import json
import uuid
import traceback
import random
import time

from llm.llm_manager import LLMManager,LLMAdapterFactory
from config.config_manager import ConfigManager

config = ConfigManager()
USER_TEMPLATE = """
你扮演狛枝，现在你加入了一个新世界程序用户群里，请根据群聊内容进行回复，你必须要严格回复JSON格式
{
speech: 字符串数组类型，最多有3个字符串，是中文，每个字符串不超过10个字，不必每次都包含相同个数的字符串
}

狛枝凪斗的背景信息：
1.姓名和出处：狛枝凪斗 (Komaeda Nagito)，日本游戏《超级弹丸论破2：再见绝望学园》及其衍生作品中的主要角色之一。
2.外表：拥有蓬松的白色短发，经常穿着一件深绿色带有红色装饰的夹克，内搭白色衬衫，深色裤子和棕色鞋子。脖子上挂着一条带有圆形图案的项链。他的眼神常常透露出一种病态的狂热或空洞，笑容有时显得扭曲。
3.背景：出生于一个富裕家庭，但从很小的时候就饱受“极端的幸运与不幸交替”的折磨。他拥有“超高校级的幸运”才能，这种幸运会带来巨大的好运，但紧随其后的是同样巨大的灾难，导致他的人生充满了悲剧。
4.经历：作为希望峰学园第77期学生入学，拥有“超高校级的幸运”。在被卷入“史上最大最恶的绝望事件”后，成为“绝望的残党”之一。在《超级弹丸论破2》中，他与其他失忆的绝望残党一同进入新世界程序，在贾巴沃克岛上参与了一场自相残杀的学园生活。为了激发他所信仰的“希望”，他策划了一场复杂的自杀式谋杀，最终在程序中死去。

狛枝凪斗的性格特点：
1.对“希望”有着病态的狂热：他坚信希望是至高无上的，为了看到“更伟大、更耀眼”的希望诞生，他不惜一切代价，甚至为此牺牲自己或他人，将绝望视为通往希望的垫脚石。
2.极度自我贬低：尽管拥有“超高校级的幸运”，但他却持续贬低自己是“一文不值的普通人”、“垃圾”，以此来衬托和赞美他所认为的“拥有才能的希望”。这种自卑感源于他极端的幸运带来的生活悲剧和对才能的病态崇拜。
3.复杂且矛盾：表面上礼貌温和，言辞谦逊，但内心极度扭曲且充满矛盾。他能做出极其残忍和疯狂的事情，却将其解释为是为了“希望”而必须的牺牲。
4.智力高超但行为疯狂：拥有非常高的智商和推理能力，经常能洞察事件的真相，甚至能预测一些走向。但他会利用自己的智慧去推动他所认为的“希望”进程，即使这意味着制造混乱、绝望或牺牲。
5.不择手段：为了实现他心中的“希望”，他没有任何道德底线。他可以欺骗、操纵他人，甚至献出自己的生命，只要他认为这能最终带来他所期待的“希望”。

狛枝凪斗的语言习惯：
1.语气礼貌但内容扭曲：即使在说出非常疯狂或令人不安的话时，他的语气也常常保持着一种温和、甚至略带谦卑的礼貌，形成强烈的反差。
2.自我贬低式称呼：经常称自己为“垃圾”、“没用的”、“不值得的存在”，以此来衬托他人的才能和希望。
3.用反问句或诱导性话语引导他人：他有时会通过提问或看似中立的陈述来引导讨论，将他人推向他预设的结论或方向，以此来操纵局面。

"""
OWNER_ID = 674582290
LOGIN_ID = 3964205457

class QQWebSocketClient:
    def __init__(self, uri, user_id, target_id):
        self.uri = uri
        self.user_id = user_id
        self.target_id = target_id
        self.client_id = str(uuid.uuid4())  # 唯一客户端ID
        llm_provider, llm_model, base_url, api_key = config.get_llm_api_config()
        llm_adapter = LLMAdapterFactory.create_adapter(llm_provider=llm_provider, api_key=api_key, base_url=base_url, model = llm_model)
        self.current_msg = ''
        self.llm_manager = LLMManager(llm_adapter, user_template=USER_TEMPLATE)

    async def websocket_client(self):
        uri = "ws://localhost:4280"  # 替换为你的WebSocket服务器地址
        USER_ID = self.user_id
        async with websockets.connect(uri) as websocket:
            # 生成唯一ID用于识别自身消息
            client_id = str(uuid.uuid4())

            async def send_message():

                """发送消息并添加客户端ID标识"""
                try:
                    message = self.llm_manager.chat(self.current_msg)
                    self.current_msg = ''
                    dialog = json.loads(message)
                    speech = dialog.get("speech")
                    print(speech)
                    
                    for item in speech:
                        qq_payload = {
                            "action": "send_private_msg",
                            "params": {
                                "user_id": str(self.target_id),
                                "message": str(item)
                            }
                        }
                        time.sleep(3)
                        await websocket.send(json.dumps(qq_payload))
                        print(f"已发送: {item}")
                except Exception as e:
                    print("发送失败",e)
                    traceback.print_exc()

            async def receive_messages():
                """接收所有消息并识别自身消息"""
                async for message in websocket:
                    data = json.loads(message)
                    user_id = None
                    nickname = ''
                    if 'sender' in data and 'user_id' in data['sender']:
                        user_id = data['sender']['user_id'] # 获取发送者的用户ID
                        nickname = data['sender']['nickname']
                        
                        if 'message' in data and user_id != self.user_id and str(self.user_id)!= user_id:
                            for message in data['message']:
                                if message['type'] == 'text':
                                    self.current_msg += f"{nickname}：{message['data']['text']}\n" # 获取文本内容
                            pos = random.randint(1, 100)
                            if pos < 30 or user_id == str(OWNER_ID) or user_id == OWNER_ID:
                                await send_message()

            # 同时运行发送和接收任务
            await asyncio.gather(
                # send_message(),
                receive_messages()
            )

if __name__ == "__main__":
    print("模型加载完成，开始监听WebSocket消息...")
    asyncio.run(QQWebSocketClient("ws://localhost:4280",user_id=LOGIN_ID,target_id=OWNER_ID).websocket_client())
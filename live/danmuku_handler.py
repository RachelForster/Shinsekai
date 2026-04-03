import asyncio
import http.cookies
import aiohttp
import threading
import time

# 假设 blivedm 已经正确安装
import blivedm
import blivedm.models.web as web_models
from core.message import UserInputMessage

# ==========================================
# 1. 定义带有“双重逻辑”的 Handler
# ==========================================
class MyHandler(blivedm.BaseHandler):
    def __init__(self, input_queue, loop):
        self.input_queue = input_queue
        self.loop = loop
        
        # 缓冲区状态
        self.msg_buffer = []
        self.timer_task = None
        self.first_msg_time = None
        
        # 配置参数
        self.DEBOUNCE_INTERVAL = 5.0  # 5秒静默触发
        self.MAX_WAIT_INTERVAL = 15.0 # 15秒强制触发

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        now = time.time()
        content = f"用户 {message.uname} 说: {message.msg}"
        
        # 1. 存入缓冲区
        self.msg_buffer.append(content)
        print(f"[收到弹幕] {content}")

        # 2. 如果是本批次第一条消息，记录开始时间
        if self.first_msg_time is None:
            self.first_msg_time = now

        # 3. 检查是否达到了 10s 硬上限
        if now - self.first_msg_time >= self.MAX_WAIT_INTERVAL:
            print(f">>> 触发硬上限 ({self.MAX_WAIT_INTERVAL}s)，强制处理消息包")
            self._flush_messages()
            return

        # 4. 重置防抖定时器
        # 只要新弹幕进来，就取消上一个定时器，重新计时 3s
        if self.timer_task is not None:
            self.timer_task.cancel()
        
        self.timer_task = self.loop.call_later(
            self.DEBOUNCE_INTERVAL, 
            self._flush_messages
        )

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        # 礼物也放入缓冲区参与批处理
        gift_content = f"系统通知: {message.uname} 送出了 {message.gift_name}x{message.num}"
        self.msg_buffer.append(gift_content)
        print(f"[收到礼物] {gift_content}")

    def _flush_messages(self):
        """核心处理逻辑：清空缓冲并发往 AI 队列"""
        if not self.msg_buffer:
            return

        # 取消可能存在的残留定时器任务
        if self.timer_task:
            self.timer_task.cancel()
            self.timer_task = None

        # 弹幕去重处理（防止复读机干扰 AI）
        unique_msgs = list(dict.fromkeys(self.msg_buffer))
        
        # 组装最终发给 LLM 的文本
        combined_text = "【弹幕汇总内容如下】\n" + "\n".join(unique_msgs)
        
        print(f"=== 正在向 AI 队列推送消息 ({len(unique_msgs)}条去重后消息) ===")
        
        # 发送至 AI 处理框架的队列
        user_msg = UserInputMessage(text=combined_text)
        self.input_queue.put(user_msg)

        # 重置所有计时状态
        self.msg_buffer = []
        self.first_msg_time = None

# ==========================================
# 2. 异步 Client 运行逻辑
# ==========================================
async def run_blivedm_client(room_id, input_queue):
    loop = asyncio.get_running_loop()
    
    # 模拟 Cookie 初始化（blivedm 库需要基本结构）
    cookies = http.cookies.SimpleCookie()
    cookies['SESSDATA'] = ''
    cookies['SESSDATA']['domain'] = 'bilibili.com'

    async with aiohttp.ClientSession() as session:
        session.cookie_jar.update_cookies(cookies)
        
        client = blivedm.BLiveClient(int(room_id), session=session)
        handler = MyHandler(input_queue, loop)
        client.set_handler(handler)

        client.start()
        print(f"--- Bilibili 弹幕监听服务已启动 ---")
        print(f"--- 当前策略: {handler.DEBOUNCE_INTERVAL}s防抖 / {handler.MAX_WAIT_INTERVAL}s硬上限 ---")
        
        try:
            await client.join()
        except Exception as e:
            print(f"Client 运行异常: {e}")
        finally:
            await client.stop_and_close()

# ==========================================
# 3. 线程包装器
# ==========================================
def run_async_loop(room_id, user_input_queue):
    """为异步循环开启独立线程"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_blivedm_client(room_id, user_input_queue))
    except Exception as e:
        print(f"异步线程崩溃: {e}")
    finally:
        loop.close()

def start_bilibili_service(room_id, user_input_queue):
    """外部调用的主入口"""
    bili_thread = threading.Thread(
        target=run_async_loop,
        args=(room_id, user_input_queue),
        daemon=True
    )
    bili_thread.start()
    print(f"Bilibili 线程已开启，后台运行中...")
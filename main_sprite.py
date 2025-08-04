from asyncio import Queue
from llm.deepseek_sprite import DeepSeek
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QApplication
from tts import tts_manager
from tts.tts_manager import TTSManager
from ui.desktop_ui import DesktopAssistantWindow
import threading
import time
import pygame
import cv2
import numpy as np
import io

class ChatWorker(QThread):
    """后台聊天工作线程"""
    update_dialog_signal = pyqtSignal(str)
    update_sprite_signal = pyqtSignal(np.ndarray)
    def __init__(self, deepseek, message, tts_manager: TTSManager = None):
        """初始化工作线程"""
        super().__init__()
        self.deepseek = deepseek
        self.message = message
        self.response_list = []
        self.tts_manager = tts_manager
        self.running = True
        self.daemon = True  # 设置为守护线程
      
        self.sprite_prefix = './data/sprite/Danganronpa_V3_Nagito_Komaeda_Bonus_Mode_Sprites_'  # 立绘图片的前缀路径
    
    def run(self):
        """在后台线程中执行聊天请求"""
        print(f"Deepseek处理消息: {self.message}")
        dialog = self.deepseek.chat(self.message)
        self.response_list = dialog if isinstance(dialog, list) else []
        if not self.response_list:
            return
        
        # 遍历响应列表中的每个item
        for item in self.response_list:
            if not self.running:
                break
                
            # 提取sprite和speech
            sprite = item.get('sprite', 'default')
            speech = item.get('speech', '')
            
            if not speech:
                continue

            # 生成语音
            if not self.tts_manager:
                print("TTS管理器未初始化")
            else:
                audio_path = self.tts_manager.generate_tts(speech, self.deepseek.text_processor)    
            # 1. 更新角色立绘
            image_path = f'{self.sprite_prefix}{sprite}.webp'
            try:
                # 使用 OpenCV 读取图像
                cv_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
                
                if cv_image is not None:
                    # 转换颜色格式 BGR -> RGBA
                    if cv_image.shape[2] == 3:  # RGB 图像
                        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
                        # 添加 alpha 通道
                        alpha_channel = np.full((cv_image.shape[0], cv_image.shape[1]), 255, dtype=np.uint8)
                        cv_image = cv2.merge([cv_image, alpha_channel])
                    elif cv_image.shape[2] == 4:  # RGBA 图像
                        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGRA2RGBA)
                    
                    self.update_sprite_signal.emit(cv_image)  # 发出更新立绘的信号
                    
                else:
                    print(f"无法加载图片: {image_path}")
            except Exception as e:
                print(f"加载图片时出错: {e}")

            # 2. 更新对话框文字
            formatted_speech = f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color: #A7CA90;'>狛枝凪斗</b>：{speech}</p>"
            self.update_dialog_signal.emit(formatted_speech)            

            # 4. 播放语音
            if audio_path:
                pygame.mixer.init()
                pygame.mixer.music.load(audio_path)
                pygame.mixer.music.play()

                # 等待音频播放完成
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                
                # 释放音频资源
                pygame.mixer.music.unload()

def handleResponse(deepseek, message, tts_manager=None, desktop_ui=None):
    """处理聊天响应"""
    print(f"处理消息: {message}")
    thread = ChatWorker(deepseek, message, tts_manager)
    if desktop_ui:
        thread.update_dialog_signal.connect(desktop_ui.setDisplayWords)
        thread.update_sprite_signal.connect(desktop_ui.update_image)
        print("连接信号到桌面UI")
    else:
        print("Desktop UI未提供，无法更新界面")
    threading.Thread(target=thread.run).start()

def main():    # 创建TTS管理器实例
    tts_manager = TTSManager()
    tts_manager.load_tts_model()  # 加载TTS模型
    
    # 创建DeepSeek实例
    deepseek = DeepSeek()

    # 创建图像队列和情感队列
    image_queue = Queue()
    emotion_queue = Queue()
    
    # 创建桌面助手窗口
    app = QApplication([])
    window = DesktopAssistantWindow(image_queue, emotion_queue, deepseek, sprite_mode=True)
    init_image = cv2.imread('./data/sprite/Danganronpa_V3_Nagito_Komaeda_Bonus_Mode_Sprites_27.webp', cv2.IMREAD_UNCHANGED)
    if init_image is not None:
        # 转换颜色格式 BGR -> RGBA
        if init_image.shape[2] == 3:  # RGB 图像
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGR2RGB)
            # 添加 alpha 通道
            alpha_channel = np.full((init_image.shape[0], init_image.shape[1]), 255, dtype=np.uint8)
            init_image = cv2.merge([init_image, alpha_channel])
        elif init_image.shape[2] == 4:  # RGBA 图像
            init_image = cv2.cvtColor(init_image, cv2.COLOR_BGRA2RGBA)
    window.update_image(init_image)  # 设置初始图像

    window.message_submitted.connect(lambda message: handleResponse(deepseek, message, tts_manager, window))

    window.show()
    app.exec_()

if __name__ == "__main__":
    main()
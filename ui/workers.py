# 
# This file is part of EasyAI Desktop Assistant in THA mode
# 

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QSize
import numpy as np

class ImageDisplayThread(QThread):
    """图像显示线程，负责从队列获取图像并更新UI"""
    update_signal = pyqtSignal(np.ndarray)
    
    def __init__(self, image_queue):
        super().__init__()
        self.image_queue = image_queue
        self.running = True
        self.font_size = "48px;"  # 默认字体大小
        
    def run(self):
        while self.running:
            try:
                if not self.image_queue.empty():
                    image = self.image_queue.get()
                    self.update_signal.emit(image)
                QThread.msleep(10)  # 10ms刷新间隔
            except Exception as e:
                print(f"Display error: {e}")

    def stop(self):
        self.running = False

class ChatWorker(QThread):
    """后台聊天工作线程"""
    response_received = pyqtSignal(dict)  # 定义信号用于传递响应

    def __init__(self, deepseek, message):
        super().__init__()
        self.deepseek = deepseek
        self.message = message
    
    def run(self):
        """在后台线程中执行聊天请求"""
        result = self.deepseek.chat(self.message)
        self.response_received.emit(result)
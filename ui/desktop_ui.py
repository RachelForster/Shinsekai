import sys
import numpy as np
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLineEdit, QSizePolicy)

class ImageDisplayThread(QThread):
    """图像显示线程，负责从队列获取图像并更新UI"""
    update_signal = pyqtSignal(np.ndarray)
    
    def __init__(self, image_queue):
        super().__init__()
        self.image_queue = image_queue
        self.running = True
        
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
    response_received = pyqtSignal(str, str)  # 定义信号用于传递响应
    
    def __init__(self, deepseek, message):
        super().__init__()
        self.deepseek = deepseek
        self.message = message
    
    def run(self):
        """在后台线程中执行聊天请求"""
        message, emotion = self.deepseek.chat(self.message)
        self.response_received.emit(message, emotion)

class DesktopAssistantWindow(QWidget):
    """桌面助手主窗口"""
    def __init__(self, image_queue, emotion_queue, deepseek):
        super().__init__()
        self.image_queue = image_queue
        self.deepseek = deepseek
        self.emotion_queue = emotion_queue
        self.chat_worker = None  # 用于处理聊天请求的工作线程
        self.original_width = 1536
        
        # 初始化UI
        self.setup_ui()
        
        # 设置图像显示线程
        self.setup_image_thread()
        
        # 初始大小
        self.resize(self.original_width, self.original_width)
        
    def setup_ui(self):
        """初始化UI组件"""
        # 窗口设置
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)
        
        # 图像容器
        self.image_container = QWidget()
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(0)
        
     
        # 图像标签
        self.setup_image_label()   
        
        # 对话框组件,覆盖在图像上
        self.setup_dialog_label()
        
        
        # 输入框布局
        input_layout = self.setup_input_layout()
        
        # 将组件添加到主布局
        main_layout.addWidget(self.image_container)
        main_layout.addLayout(input_layout)
        
        self.setLayout(main_layout)
    
    def setup_dialog_label(self):
        """初始化对话框标签"""
        self.dialog_label = QLabel("")
        self.dialog_label.setTextFormat(Qt.RichText)
        self.dialog_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.dialog_label.setStyleSheet("""
            QLabel {
                background-color: rgba(50, 50, 50, 200);
                color: #f0f0f0;
                font-size: 36px;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                padding: 20px; 
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                line-height: 200%;
                letter-spacing: 2px;
            }
        """)
        self.dialog_label.setWordWrap(True)
        self.dialog_label.hide()
        self.dialog_label.setParent(self.image_container)
    
    def setup_image_label(self):
        """初始化图像标签"""
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_layout.addWidget(self.label)
    
    def setup_input_layout(self):
        """初始化输入布局"""
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        # 输入框
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入消息...")
        self.input_box.setStyleSheet("""
            QLineEdit {
                background-color: rgba(50, 50, 50, 200);
                color: white;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                border: 1px solid #555;
                border-radius: 5px;
                padding: 20px;
                font-size: 28px;
            }
        """)
        self.input_box.returnPressed.connect(self.sendMessage)
        
        # 发送按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px;
                font-size: 28px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.send_btn.clicked.connect(self.sendMessage)
        
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_btn)
        
        return input_layout
    
    def setup_image_thread(self):
        """设置图像显示线程"""
        self.display_thread = ImageDisplayThread(self.image_queue)
        self.display_thread.update_signal.connect(self.update_image)
        self.display_thread.start()
    
    def update_image(self, image):
        """更新显示图像"""
        self.original_image = image
        height, width, channel = image.shape
        bytes_per_line = 4 * width
        qimg = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        
        # 将图像放大
        rate = self.original_width / 1024
        scaled_pixmap = pixmap.scaled(
            int(width * rate), 
            int(height * rate),
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        
        # 设置放大后的图像
        self.label.setPixmap(scaled_pixmap)
        self.label.setFixedSize(self.original_width, self.original_width)
        self.adjustSize()
    
    def sendMessage(self):
        """发送消息函数"""
        message = self.input_box.text().strip()
        if message:
            print(f"发送消息: {message}")
            self.input_box.clear()
            self.setDisplayWords(f"<b>你</b>：{message}")
            
            # 创建并启动聊天工作线程
            self.chat_worker = ChatWorker(self.deepseek, message)
            self.chat_worker.response_received.connect(self.handleResponse)
            self.chat_worker.start()
    
    def handleResponse(self, message, emotion):
        """处理聊天响应"""
        self.setDisplayWords(f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color: #A7CA90;'>狛枝凪斗</b>：{message}</p>")
        if not self.emotion_queue.full():
            self.emotion_queue.put(emotion)
    
    def setDisplayWords(self, text):
        """显示人物说的话"""
        if text:
            self.dialog_label.setText(text)
            self.dialog_label.show()
            self.dialog_label.adjustSize()
            y = self.label.height() - self.dialog_label.height()
            self.dialog_label.setGeometry(0, y, self.label.width(), self.dialog_label.height())
        else:
            self.dialog_label.hide()
    
    def mousePressEvent(self, event):
        """实现窗口拖动"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """拖动窗口"""
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def closeEvent(self, event):
        """关闭窗口时停止线程"""
        self.display_thread.stop()
        self.display_thread.wait()
        super().closeEvent(event)

def start_qt_app(display_queue, emotion_queue, deepseek):
    """启动PyQt应用"""
    app = QApplication(sys.argv)
    window = DesktopAssistantWindow(display_queue, emotion_queue, deepseek)
    print("QT Window starts!!")
    window.show()
    sys.exit(app.exec_())
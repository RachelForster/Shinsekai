import sys
import numpy as np
import threading
import time
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, QMenu, QAction,QDialog, QListWidget, QListWidgetItem,
                             QHBoxLayout, QPushButton, QLineEdit, QSizePolicy)
import os

class MessageDialog(QDialog):
    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("对话历史记录")
        self.setModal(True)
        self.resize(600, 400)
        
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("对话历史记录")
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(14)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # 消息列表
        self.message_list = QListWidget()
        self.message_list.setAlternatingRowColors(True)
        
        # 添加消息到列表
        for msg in messages:
            item_widget = self.create_message_widget(msg)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            self.message_list.addItem(list_item)
            self.message_list.setItemWidget(list_item, item_widget)
        
        layout.addWidget(self.message_list)
        self.setLayout(layout)
    
    def create_message_widget(self, message):
        widget = QLabel()
        widget.setMargin(10)
        widget.setWordWrap(True)
        widget.setTextFormat(Qt.RichText)
        
        # 设置样式
        widget.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        # 格式化消息
        formatted_text = f"<b>{message['username']}</b>: {message['speech']}"
        widget.setText(formatted_text)
        
        # 调整大小以适应内容
        widget.adjustSize()
        
        return widget


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
    response_received = pyqtSignal(str, str)  # 定义信号用于传递响应
    
    def __init__(self, deepseek, message):
        super().__init__()
        self.deepseek = deepseek
        self.message = message
    
    def run(self):
        """在后台线程中执行聊天请求"""
        result = self.deepseek.chat(self.message)
        self.response_received.emit(result)

class DesktopAssistantWindow(QWidget):
    """桌面助手主窗口"""
    message_submitted = pyqtSignal(str)  # 定义信号用于发送消息
    def __init__(self, image_queue, emotion_queue, deepseek, sprite_mode=False):
        """初始化窗口"""
        super().__init__()
        self.image_queue = image_queue
        self.display_thread = None
        self.deepseek = deepseek
        self.emotion_queue = emotion_queue
        self.sprite_mode = sprite_mode
        self.original_width = 1536
        self.font_size = "48px;"  # 默认字体大小
        
        # 设置图像显示线程
        if not self.sprite_mode:
            self.setup_image_thread()
        
        # 初始大小
        self.resize(self.original_width, self.original_width)

        self.setup_ui()
        
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

        # 工具栏
        self.setup_toolbar()
        
        # 输入框布局
        input_layout = self.setup_input_layout()
        
        # 将组件添加到主布局
        main_layout.addWidget(self.image_container)
        main_layout.addLayout(input_layout)
        
        self.setLayout(main_layout)
    
    def setup_toolbar(self):
        """初始化右上角工具栏"""
        # 创建工具栏容器
        self.toolbar = QWidget(self.image_container)
        self.toolbar.setFixedSize(140, 48)
        self.toolbar.move(self.width() - 150, 10)
        self.toolbar.setStyleSheet("background-color: rgba(50, 50, 50, 150); border-radius: 20px;")
        
        # 工具栏布局
        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(16, 0, 16, 0)
        toolbar_layout.setSpacing(8)
        
        # 设置按钮
        button_size = 48
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(button_size, button_size)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 100);
                border: 2px solid rgba(255, 255, 255, 150);
                border-radius: 24px;
                color: white;
                font-size: 28px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 150);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 200);
            }
        """)
        self.settings_btn.clicked.connect(self.show_settings_menu)
        
        # 关闭按钮
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(button_size, button_size)
        self.close_btn.setStyleSheet("""
             QPushButton {
                background-color: rgba(255, 255, 255, 100);
                border: 2px solid rgba(255, 255, 255, 150);
                border-radius: 24px;
                color: white;
                font-size: 28px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 150);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 200);
            }
        """)
        self.close_btn.clicked.connect(self.close)
        
        # 添加到工具栏布局
        toolbar_layout.addWidget(self.settings_btn)
        toolbar_layout.addWidget(self.close_btn)
    
    def show_settings_menu(self):
        """显示设置下拉菜单"""
        menu = QMenu(self)

        print("show settings")
        
        # 添加菜单项
        history_action = QAction("历史记录", self)
        language_action = QAction("语音语言", self)
        donate_action = QAction("赞赏作者", self)
        
        # 连接菜单项的信号
        history_action.triggered.connect(self.show_history)
        language_action.triggered.connect(self.show_language_settings)
        donate_action.triggered.connect(self.show_donate)
        
        # 添加菜单项到菜单
        menu.addAction(history_action)
        menu.addAction(language_action)
        menu.addAction(donate_action)
        
        # 显示菜单在设置按钮下方
        menu.exec_(self.settings_btn.mapToGlobal(
            self.settings_btn.rect().bottomLeft()
        ))
    
    def show_history(self):
        """显示历史记录"""
        print("显示历史记录功能")
        messages = self.get_messages_from_service()
        
        # 创建并显示对话框
        dialog = MessageDialog(messages, self)
        dialog.exec_()
    
    # TODO 写一下如何从外部获取对话记录
    def get_messages_from_service(self):
        # 模拟从外部服务获取数据
        # 在实际应用中，这里可能是API调用、数据库查询等
        return [
            {"username": "张三", "speech": "你好，今天天气真不错！"},
            {"username": "李四", "speech": "是的，很适合出去散步。"},
            {"username": "张三", "speech": "你有什么计划吗？"},
            {"username": "李四", "speech": "我打算去公园看书，你要一起来吗？"},
            {"username": "张三", "speech": "好主意！半小时后公园门口见。"},
            {"username": "王五", "speech": "你们在讨论什么？我可以加入吗？"},
            {"username": "李四", "speech": "当然欢迎！我们打算去公园，一起吧！"},
            {"username": "王五", "speech": "太棒了！我等会儿带些点心过去。"},
            {"username": "张三", "speech": "完美！那我们等会儿见。"}
        ]

        # 这里可以添加显示历史记录的具体实现
    
    def show_language_settings(self):
        """显示语音语言设置"""
        print("显示语音语言设置功能")
        # 这里可以添加语音语言设置的具体实现
    
    def show_donate(self):
        """显示赞赏作者界面"""
        print("显示赞赏作者功能")
        # 这里可以添加赞赏作者的具体实现

    def setup_dialog_label(self):
        """初始化对话框标签"""
        self.dialog_label = QLabel("")
        self.dialog_label.setTextFormat(Qt.RichText)
        self.dialog_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.dialog_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(50, 50, 50, 200);
                color: #f0f0f0;
                font-size: {self.font_size};
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                padding: 20px; 
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                line-height: 200%;
                letter-spacing: 2px;
            }}
        """)
        self.dialog_label.setWordWrap(True)
        self.dialog_label.hide()
        self.dialog_label.setParent(self.image_container)
    
    def setup_image_label(self):
        """初始化图像标签"""
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
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
                border-radius: 10px;
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
        
        # # 将图像放大
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
            print(f"UI发送消息: {message}")
            self.input_box.clear()
            self.setDisplayWords(f"<b>你</b>：{message}")
            self.input_box.setPlaceholderText("发送成功喵，等待回复中……")
            
            # 创建并启动聊天工作线程
            if self.sprite_mode is False:
                self.chat_worker = ChatWorker(self.deepseek, message)
                self.chat_worker.response_received.connect(self.handleResponse)
                self.chat_worker.start()

            self.message_submitted.emit(message)  # 发出消息提交信号

    def setNotification(self, message):
        """设置提示词"""
        self.input_box.setPlaceholderText(message)

    def handleResponse(self, result):
        """处理聊天响应"""
        if not self.sprite_mode:
            self.setDisplayWords(f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color: #A7CA90;'>狛枝凪斗</b>：{result['message']}</p>")
            if not self.emotion_queue.full():
                self.emotion_queue.put(result['emotion'])

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
        if self.display_thread:
            self.display_thread.stop()
            self.display_thread.wait()
        super().closeEvent(event)
        # 强制终止进程
        os._exit(0)

def start_qt_app(display_queue, emotion_queue, deepseek):
    """启动PyQt应用"""
    app = QApplication(sys.argv)
    window = DesktopAssistantWindow(display_queue, emotion_queue, deepseek)
    print("QT Window starts!!")
    window.show()
    sys.exit(app.exec_())

import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import time
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, QMenu, QAction,QDialog, QListWidget, QListWidgetItem, QButtonGroup, QRadioButton,
                             QHBoxLayout, QPushButton, QLineEdit, QSizePolicy)
import os


class LanguageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择语言")
        self.setModal(True)
        
        # 设置半透明黑色背景
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                border-radius: 10px;
                color: white;
            }
            QRadioButton {
                color: white;
                padding: 8px;
                font-size: 14px;
            }
            QRadioButton::indicator {
                width: 20px;
                height: 20px;
                border-radius: 10px;
                border: 2px solid white;
            }
            QRadioButton::indicator:checked {
                background-color: #4CAF50;
                border: 2px solid white;
            }
            QPushButton {
                background-color: rgba(76, 175, 80, 200);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(76, 175, 80, 255);
            }
            QPushButton:pressed {
                background-color: rgba(62, 142, 65, 255);
            }
        """)
        
        self.init_ui()
        self.adjustSize()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # 语言选项
        self.language_group = QButtonGroup(self)
        
        # 英语选项
        self.english_radio = QRadioButton("English")
        self.language_group.addButton(self.english_radio, 0)
        layout.addWidget(self.english_radio)
        
        # 中文选项
        self.chinese_radio = QRadioButton("中文")
        self.language_group.addButton(self.chinese_radio, 1)
        layout.addWidget(self.chinese_radio)
        
        # 日语选项
        self.japanese_radio = QRadioButton("日本語")
        self.language_group.addButton(self.japanese_radio, 2)
        layout.addWidget(self.japanese_radio)
        
        # 粤语选项
        self.cantonese_radio = QRadioButton("粵語")
        self.language_group.addButton(self.cantonese_radio, 3)
        layout.addWidget(self.cantonese_radio)
        
        # 默认选择英语
        self.english_radio.setChecked(True)
        
        # 确认按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.confirm_button = QPushButton("确定")
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
        
    def get_selected_language(self):
        selected_id = self.language_group.checkedId()
        languages = {
            0: "en",
            1: "zh",
            2: "ja",
            3: "yue"
        }
        return languages.get(selected_id, "en")

# 消息历史对话框
class MessageDialog(QDialog):
    def __init__(self, messages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("对话历史记录")
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setModal(True)
        self.resize(800, 600)
        
        # 设置半透明黑背景
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                color: white;
                border-radius: 10px;
            }
            QListWidget {
                background-color: rgba(255, 255, 255, 30);
                alternate-background-color: rgba(255, 255, 255, 50);
                color: white;
                border: none;
                border-radius: 5px;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 255, 255, 100);
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)  # 添加边距
        
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
        
        # 设置样式 - 调整为深色主题
        widget.setStyleSheet("""
            QLabel {
                background-color: rgba(60, 60, 60, 180);
                color: white;
                font-size: 28px;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        # 格式化消息内容
        widget.setText(message)
        
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
    response_received = pyqtSignal(dict)  # 定义信号用于传递响应

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
    open_chat_history_dialog = pyqtSignal()  # 定义信号用于打开聊天历史记录对话框
    change_voice_language = pyqtSignal(str)  # 定义信号用于更改语音的语言
    def __init__(self, image_queue, emotion_queue, llm_manager, sprite_mode=False):
        """初始化窗口"""
        super().__init__()
        self.image_queue = image_queue
        self.display_thread = None
        self.deepseek = llm_manager
        self.emotion_queue = emotion_queue
        self.sprite_mode = sprite_mode
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        self.original_width = min(screen_geometry.height(), screen_geometry.width()) // 4 * 3
        self.original_height = self.original_width
        self.font_size = "48px;"  # 默认字体大小

        # 设置图像显示线程
        if not self.sprite_mode:
            self.setup_image_thread()
        
        # 初始大小
        self.resize(self.original_width, self.original_height)

        # 初始化UI组件
        self.setup_ui()

        # 居中显示
        self.move((screen_geometry.width() - self.original_width) // 2, 
                  (screen_geometry.height() - self.original_height - 200))

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
        self.toolbar.move(self.original_width - 150, 10)
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
        
        # 连接菜单项的信号
        history_action.triggered.connect(lambda: self.open_chat_history_dialog.emit())
        language_action.triggered.connect(self.show_language_settings)
        
        # 添加菜单项到菜单
        menu.addAction(history_action)
        menu.addAction(language_action)
        
        # 显示菜单在设置按钮下方
        menu.exec_(self.settings_btn.mapToGlobal(
            self.settings_btn.rect().bottomLeft()
        ))

    def open_history_dialog(self, messages):
        # 创建并显示对话框
        dialog = MessageDialog(messages, self)
        dialog.exec_()
    
    def show_language_settings(self):
        """显示语音语言设置"""
        dialog = LanguageDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            selected_language = dialog.get_selected_language()
            print(f"选择的语言: {selected_language}")
            self.change_voice_language.emit(selected_language)
            language_str = ""
            if selected_language == "en":
                language_str = "English"
            elif selected_language == "zh":
                language_str = "中文"
            elif selected_language == "ja":
                language_str = "日本語"
            elif selected_language == "yue":
                language_str = "粵語"
            self.setNotification("语音语言已更改:" + language_str)

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
        scaled_with = max(1024, width)
        rate = self.original_width / scaled_with
        scaled_pixmap = pixmap.scaled(
            int(width * rate), 
            int(height * rate),
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        
        # 设置放大后的图像
        self.label.setPixmap(scaled_pixmap)
        self.label.setFixedSize(self.original_height, self.original_width)
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

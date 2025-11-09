import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import pygame
import yaml
import time
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QSize, QUrl
from PyQt5.QtWidgets import QSlider,QMessageBox
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, QMenu, QAction,QDialog, QListWidget, QListWidgetItem, QButtonGroup, QRadioButton,
                             QHBoxLayout, QPushButton, QLineEdit, QSizePolicy)
import os

from pathlib import Path

import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.components import VolumeDialog, ClickableLabel, MessageDialog, LanguageDialog, FontSizeDialog, TypingLabel, SpritePanel, ThemeColorDialog
from ui.workers import ImageDisplayThread, ChatWorker
from config.config_manager import ConfigManager

config_manager = ConfigManager()

DIALOG_FRAME_PATH = Path('./assets/system/picture/dialog_frame.png').absolute().as_posix()
class DesktopAssistantWindow(QWidget):
    """桌面助手主窗口"""
    message_submitted = pyqtSignal(str)  # 定义信号用于发送消息
    open_chat_history_dialog = pyqtSignal()  # 定义信号用于打开聊天历史记录对话框
    change_voice_language = pyqtSignal(str)  # 定义信号用于更改语音的语言
    close_window = pyqtSignal() #关闭窗口信号
    clear_chat_history = pyqtSignal()
    skip_speech_signal = pyqtSignal() # 跳过当前语音信号

    def __init__(self, image_queue, emotion_queue, llm_manager, sprite_mode=False, background_mode = False, max_sprite_slots=3):
        """初始化窗口"""
        super().__init__()
        self.CONFIG_FILE = './data/config/system_config.yaml'
        if background_mode:
            self.HORIZONTAL_MARGIN_PERCENT = 0.2
        else:
            self.HORIZONTAL_MARGIN_PERCENT = 0
        self.image_queue = image_queue
        self.display_thread = None
        self.max_sprite_slots = max_sprite_slots
        self.deepseek = llm_manager
        self.emotion_queue = emotion_queue
        self.sprite_mode = sprite_mode
        self.current_options = []
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        self.original_height = screen_geometry.height() // 4 * 3
        self.original_width = screen_geometry.width() // 4 * 3 if background_mode else self.original_height

        self.config = self._read_config()
        self.base_font_size_px = self.config.get('base_font_size_px', 48)

        # 设置字体大小
        base_dpi = 150.0
        curren_dpi = screen.logicalDotsPerInch()
        self.font_size = f"{str(int(self.base_font_size_px*curren_dpi//base_dpi))}px;"
        self.btn_font_size = f"{str(int(self.base_font_size_px*curren_dpi//base_dpi))}px;"

        # 对话框颜色
        self.theme_color = config_manager.config.system_config.theme_color
        self.second_color = 'rgba(50, 50, 50, 100)'

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
        self.setWindowFlags(Qt.FramelessWindowHint |  Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)
        
        self.setup_background_label()        
        # 图像容器
        self.image_container = QWidget()
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(0)

        # 数值信息标签
        self.setup_numeric_label()

        # 图像标签
        self.setup_image_label()   
        
        # 对话框组件,覆盖在图像上
        self.setup_dialog_label()

        # 选项容器,与对话框标签位置相同
        self.setup_options_widget()

        # 工具栏
        self.setup_toolbar()
        
        # 输入框布局
        input_layout = self.setup_input_layout()
        
        # 将组件添加到主布局
        main_layout.addWidget(self.image_container)
        main_layout.addLayout(input_layout)
        
        self.background_label.lower()

        self.setLayout(main_layout)

        self.apply_font_styles()
    
    def apply_font_styles(self):
        """根据当前的 font_size 和 btn_font_size 更新所有UI元素的样式"""
        # Recalculate DPI scaled sizes
        screen = QApplication.primaryScreen()
        curren_dpi = screen.logicalDotsPerInch()
        base_dpi = 150.0
        
        self.font_size = f"{str(int(self.base_font_size_px*curren_dpi//base_dpi))}px;"
        # Button font is scaled relative to the default dialog font (48px)
        self.btn_font_size = f"{str(int(self.base_font_size_px*28//48*curren_dpi//base_dpi))}px;" 
        
        # Apply to dialog label
        df_pixel_map = QPixmap(DIALOG_FRAME_PATH)
        
        self.dialog_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(50, 50, 50, 200);
                color: #f0f0f0;
                font-size: {self.font_size};
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                padding: 16px; 
                border-radius: 16px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                line-height: 200%;
                letter-spacing: 2px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1, 
                    stop: 0   {self.theme_color},      
                    stop: 1   {self.second_color}     
                );
            }}
        """)
        self.dialog_label.setPixmap(df_pixel_map)
        
        # Apply to numeric label
        self.numeric_info_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 100); /* 半透明黑色背景 */
                padding: 12px;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                font-size: {self.font_size};
                line-height: 150%;
                border-radius: 16px;
                color: white; /* 白色字体 */
                border-image: url({QUrl.fromLocalFile(DIALOG_FRAME_PATH).toString()}) 15 15 15 15 stretch;
                border-width: 15px; 
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1, 
                    stop: 0   {self.theme_color},      
                    stop: 1   {self.second_color}     
                );
            }}
        """)
        
        # Apply to input box
        self.input_box.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(50, 50, 50, 200);
                color: white;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                border: 1px solid #555;
                border-radius: 5px;
                padding: 20px;
                font-size: {self.btn_font_size};
            }}
        """)
        
        # Apply to send button
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme_color};
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                color: white;
                border: none;
                border-radius: 10px;
                padding: 20px;
                font-size: {self.btn_font_size}
            }}
            QPushButton:hover {{
                background-color: rgba(50, 50, 50, 200);
            }}
        """)
        
        # Re-apply styles to any existing options (if visible/available)
        for i in range(self.options_layout.count()):
            item = self.options_layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                 widget.setStyleSheet(f"""
                    QLabel {{
                        background-color: rgba(255, 255, 255, 50);
                        color: white;
                        border-radius: 6px;
                        padding: 5px;
                        text-align: left;
                        font-size: {self.font_size};
                        min-height: 40px;
                    }}
                    QLabel:hover {{
                        background-color: rgba(255, 255, 255, 30);
                        border: 1px solid;
                    }}
                """)

        # Since sizes changed, force a re-layout/adjust
        self.dialog_label.adjustSize()
        self.numeric_info_label.adjustSize()
        if self.options_widget.isVisible():
            self.setDisplayWords("Test")
            self.setOptions(self.current_options)

    
    def show_font_size_settings(self):
        """显示字体大小设置对话框"""
        dialog = FontSizeDialog(self.base_font_size_px, self)
        if dialog.exec_() == QDialog.Accepted:
            new_size = dialog.get_new_font_size()
            if new_size != self.base_font_size_px:
                self.base_font_size_px = new_size
                
                # 1. 更新配置并写入文件
                self.config['base_font_size_px'] = new_size
                self._write_config() # 写入 YAML 文件
                
                # 2. 动态更新所有UI的字体样式
                self.apply_font_styles()
                
                self.setNotification(f"字体大小已更改为 {new_size}px")

    def setup_toolbar(self):
        """初始化右上角工具栏"""
        # 创建工具栏容器
        self.toolbar = QWidget(self.image_container)
        self.toolbar.setFixedSize(200, 48)
        self.toolbar.move(self.original_width - 200, 10)
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

        # 最小化按钮
        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setFixedSize(button_size, button_size)
        self.minimize_btn.setStyleSheet("""
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
        self.minimize_btn.clicked.connect(self.minimize_window)

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
        toolbar_layout.addWidget(self.minimize_btn)
        toolbar_layout.addWidget(self.close_btn)
    
    def show_settings_menu(self):
        """显示设置下拉菜单"""
        menu = QMenu(self)
        
        # 添加菜单项
        history_action = QAction("历史记录", self)
        clear_history_action = QAction("清空历史记录",self)
        language_action = QAction("语音语言", self)
        font_size_action = QAction("字体大小", self)
        volumn_action = QAction("音量", self)
        theme_color_action = QAction("主题色",self)
        
        # 连接菜单项的信号
        history_action.triggered.connect(lambda: self.open_chat_history_dialog.emit())
        language_action.triggered.connect(self.show_language_settings)
        clear_history_action.triggered.connect(self.clear_history)
        font_size_action.triggered.connect(self.show_font_size_settings)
        volumn_action.triggered.connect(self.show_volumn_settings)
        theme_color_action.triggered.connect(self.show_theme_color_dialog)

        # 添加菜单项到菜单
        menu.addAction(history_action)
        menu.addAction(clear_history_action)
        menu.addAction(language_action)
        menu.addAction(font_size_action)
        menu.addAction(volumn_action)
        menu.addAction(theme_color_action)
        
        
        # 显示菜单在设置按钮下方
        menu.exec_(self.settings_btn.mapToGlobal(
            self.settings_btn.rect().bottomLeft()
        ))
    def show_volumn_settings(slef):
        dialog = VolumeDialog(config_manager.config.system_config.music_volumn)
        if dialog.exec_() == QDialog.Accepted:
            selected_volumn = dialog.get_new_volume()
            config_manager.config.system_config.music_volumn = selected_volumn
            config_manager.save_system_config()
            pygame.mixer.music.set_volume(selected_volumn/100)

    def clear_history(self):
        reply = QMessageBox.question(
            self,                                 # 父窗口 (parent)
            '确认',                           # 窗口标题 (title)
            "您确定要清除历史吗？。", # 提示信息 (text)
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, # 按钮组合
            QMessageBox.StandardButton.No        # 默认选中的按钮（按回车键时的默认操作）
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.clear_chat_history.emit()
    def open_history_dialog(self, messages):
        # 创建并显示对话框
        dialog = MessageDialog(messages, self)
        dialog.exec_()
    
    def show_theme_color_dialog(self):
        dialog = ThemeColorDialog(self.theme_color)
        if dialog.exec_() == QDialog.Accepted:
            self.theme_color = dialog.get_selected_color()
            config_manager.config.system_config.theme_color = self.theme_color
            self.apply_font_styles()
            self.setNotification("主题颜色已更改" + self.theme_color)
            config_manager.save_system_config()

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

            config_manager.config.system_config.voice_language = selected_language
            config_manager.save_system_config()
            self.setNotification("语音语言已更改:" + language_str)

    def setup_numeric_label(self):
        # 1. 创建用于显示富文本的“数值组件”
        self.numeric_info_label = QLabel(self.image_container) # 以 self.label (图像容器) 为父组件
        # 允许显示富文本（HTML 格式）
        self.numeric_info_label.setTextFormat(Qt.RichText) 
        # 设置初始文本（示例）
        self.numeric_info_label.setWordWrap(True)
        self.numeric_info_label.setText("<b>HP:</b> <span style='color:red;'>100</span>")
        
        # 3. 设置半透明背景和字体颜色
        # 为了覆盖图像，设置一个半透明背景，并确保文字清晰可见
        self.numeric_info_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 100); /* 半透明黑色背景 */
                padding: 12px;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                font-size: {self.font_size};
                line-height: 150%;
                border-radius: 16px;
                color: white; /* 白色字体 */
            }}
        """)
        
        # 4. 调整大小策略：根据内容自动调整
        self.numeric_info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 5. 初始隐藏（如果需要，你也可以直接显示）
        self.numeric_info_label.hide() 

    def setup_dialog_label(self):
        """初始化对话框标签"""
        self.dialog_label = TypingLabel()
        self.dialog_label.clicked.connect(lambda: self.skip_speech_signal.emit()) 
        self.dialog_label.setTextFormat(Qt.RichText)
        self.dialog_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.dialog_label.setStyleSheet(f"""
            QLabel {{
                background-color: rgba(50, 50, 50, 200);
                color: #f0f0f0;
                font-size: {self.font_size};
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                padding: 40px; 
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                line-height: 200%;
                letter-spacing: 2px;
                border-image: url({DIALOG_FRAME_PATH}) 40 40 40 40 stretch;
                border-width: 40px;
            }}
        """)
        self.dialog_label.setWordWrap(True)
        self.dialog_label.hide()
        self.dialog_label.setParent(self.image_container)

        self.skip_button = QPushButton(">")
        self.skip_button.setParent(self.image_container)
        self.skip_button.setFixedSize(48, 48)
        self.skip_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0);
                color: white;
                border: none;
                border-radius: 24px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 100, 100, 100);
            }
        """)
        # 4. 连接按钮到跳过信号
        self.skip_button.hide()

    def setup_options_widget(self):
        """初始化选项容器，与对话框标签位置相同"""
        self.options_widget = QWidget()
        
        # 设置容器的基本样式，与dialog_label相似
        self.options_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(50, 50, 50, 200); /* 与dialog_label背景相似 */
                border-radius: 12px;
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
            }
        """)
        
        self.options_layout = QVBoxLayout(self.options_widget)
        self.options_layout.setContentsMargins(15, 15, 15, 15) # 稍微大一点的边距
        self.options_layout.setSpacing(10)
        
        # 设置父组件，使其覆盖在图像上
        self.options_widget.setParent(self.image_container)
        self.options_widget.hide()

    def setup_image_label(self):
        """初始化立绘标签"""
        self.sprite_panel = SpritePanel(self.original_width, self.original_height, max_slots_num=self.max_sprite_slots)
        # self.label = CrossFadeSprite(self.original_width, self.original_height)
        # self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_layout.addWidget(self.sprite_panel)
    
    def setup_input_layout(self):
        """初始化输入布局"""
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        # 输入框
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入消息...")
        self.input_box.setStyleSheet(f"""
            QLineEdit {{
                background-color: rgba(50, 50, 50, 200);
                color: white;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                border: 1px solid #555;
                border-radius: 5px;
                padding: 20px;
                font-size: {self.btn_font_size};
            }}
        """)
        self.input_box.returnPressed.connect(self.sendMessage)
        
        # 发送按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 10px;
                padding: 10px;
                font-size: {self.btn_font_size}
            }}
            QPushButton:hover {{
                background-color: #45a049;
            }}
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

    def setup_background_label(self):
        self.background_label = QLabel(self)
        self.background_label.setGeometry(0, 0, self.original_width, self.original_height)
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setBackgroundImage(self, image_path: str):
        """
        设置窗口背景图片，图片将缩放填充整个窗口。
        
        :param image_path: 背景图片文件的路径。
        """
        self.sprite_panel.remove_all()  # 清除所有立绘显示
        if not os.path.exists(image_path):
            print(f"Background image file not found: {image_path}")
            # 可以设置一个纯色背景作为 fallback
            self.background_label.setStyleSheet("background-color: white;")
            self.background_label.setText("背景图加载失败")
            return

        # 使用 QPixmap 加载图片
        pixmap = QPixmap(image_path)
        
        # 动态设置样式表，使用 border-image 来实现背景填充和缩放
        # 设置 background_label 的样式表
        style = f"""
            QLabel {{
                background-image: url({image_path});
                background-repeat: no-repeat;
                background-position: center;
                background-color: #333333; 
                border-radius: 24px;
            }}
        """
        # 更可靠的方式是使用 QPixmap 和 QLabel.setPixmap，并手动缩放
        
        # 重新设置背景图片
        scaled_pixmap = pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.background_label.setPixmap(scaled_pixmap)
        self.background_label.lower()

    def update_image(self, image, character_name="", scale_rate=1.0):
        """更新显示图像"""
        self.original_image = image
        if image.size == 0:
            self.sprite_panel.remove(character_name)
        else:
             self.sprite_panel.switch_sprite(character_name, image, scale_rate)

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
    
    def update_numeric_info(self, html_text: str):
        """
        更新数值组件显示的富文本内容。
        例如: window.update_numeric_info("<b>EXP:</b> <span style='color:lime;'>+15</span>")
        """
        self.numeric_info_label.setText(html_text)
        
        # 内容变化后，需要重新调整大小并重新定位
        self.numeric_info_label.adjustSize()
        
        # 如果内容为空，隐藏组件
        if not html_text.strip():
            self.numeric_info_label.hide()
        else:
            self.numeric_info_label.show()
            self.numeric_info_label.raise_()

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
            self.options_widget.hide()
            self.dialog_label.setText(text)
            container_width = self.original_width # 使用 self.original_width 作为容器宽度
            margin_width = int(container_width * self.HORIZONTAL_MARGIN_PERCENT)
            new_width = container_width - (2 * margin_width)

            self.dialog_label.setFixedWidth(new_width) 
            self.dialog_label.adjustSize()
            height = max(int(self.original_height * 0.3), self.dialog_label.height())
            
            # 2. 计算垂直位置 (保持在底部)
            y = self.original_height - height
            
            # 3. 设置居中的位置和调整后的尺寸
            self.dialog_label.setGeometry(margin_width, y, new_width, height)

            self.dialog_label.show()
            self.dialog_label.setDisplayWords(text) # 启动打字机效果
            
            # 4. 调整跳过按钮的位置
            self.skip_button.move(
                self.dialog_label.geometry().right() - self.skip_button.width() - 20, 
                self.dialog_label.geometry().bottom() - self.skip_button.height() - 10
            )
            self.skip_button.show()
        else:
            self.dialog_label.hide()
            self.skip_button.hide() # 隐藏跳过按钮
    
    def option_clicked(self, text):
        """选项按钮点击处理函数"""
        print(f"Option clicked: {text}")
        self.input_box.setText(text) # 将内容添加到输入框
        self.setOptions([])          # 隐藏选项
        self.sendMessage()           # 自动发送消息
    
    def setOptions(self, optionList: list[str]):
        """
        在dialog label相同的地方显示一组半透明选项按钮，并隐藏dialog label。
        
        点击选项按钮会将内容添加到输入框并发送。
        """
        self.current_options = optionList
        print(f"Setting options: {optionList}")
        # 1. 互斥：隐藏对话框标签
        self.dialog_label.hide() 

        # 2. 清除现有按钮
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not optionList:
            # 3. 如果列表为空，隐藏选项容器并返回
            self.options_widget.hide()
            return

        try:
            content = self.theme_color.strip().replace('rgba(', '').replace(')', '')
            r, g, b, a = map(int, content.split(','))
        # 创建一个非常低的透明度版本 (例如 10%) 作为背景柔和光晕
            low_opacity_theme = f"rgba({r}, {g}, {b}, 50)" 
        except Exception:
            low_opacity_theme = "rgba(50, 50, 50, 25)"

        # 4. 添加新按钮
        for option_text in optionList:
            option_btn = ClickableLabel()
            option_btn.setText(option_text)
            option_btn.setTextFormat(Qt.RichText)
            option_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            option_btn.setWordWrap(True)
            
            # 设置半透明样式，使用主题色和字体大小
            option_btn.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba(255, 255, 255, 50);
                    color: white;
                    border-radius: 6px;
                    padding: 9px;
                    text-align: left;
                    font-size: {self.font_size};
                    min-height: 40px;
                    background: qlineargradient(
                        x1: 0, y1: 0, x2: 1, y2: 0, 
                        stop: 0   {self.theme_color},      
                        stop: 1   {self.second_color}     
                    );
                }}
                QLabel:hover {{
                background-color: {low_opacity_theme};
                border-bottom: 5px solid {self.theme_color}; 
                color: white; 
                padding: 9px 20px 11px 20px;
            }}

            QLabel:pressed {{
                /* 按下状态：模拟点击反馈 */
                background-color: {self.theme_color};
                color: white;
            }}
            """)
            
            # 连接点击事件，使用 lambda 传递选项内容
            option_btn.clicked.connect(lambda text=option_text: self.option_clicked(text))
            self.options_layout.addWidget(option_btn)

        container_width = self.original_width # 使用 self.original_width 作为容器宽度
        margin_width = int(container_width * self.HORIZONTAL_MARGIN_PERCENT)
        new_width = container_width - (2 * margin_width)
        
        # 5a. 临时设置宽度来获取正确的 sizeHint (高度)
        self.options_widget.setFixedWidth(new_width)
        
        # 5b. 获取适应新宽度后的高度
        final_height = self.options_widget.sizeHint().height()
        
        # 6. 放置在图像标签的底部
        y = self.original_height - final_height
        
        # 7. 设置居中的位置和最终的尺寸
        self.options_widget.setGeometry(margin_width, y, new_width, final_height)
        # 7. 显示选项
        self.options_widget.show()
        # 确保在图像和其他元素上方显示 (工具栏和对话框标签除外)
        self.options_widget.raise_()
        self.toolbar.raise_()
    def minimize_window(self):
        """
        调用 QWidget 的 showMinimized() 方法来最小化窗口。
        """
        self.showMinimized()
        print("窗口已最小化")

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
        self.close_window.emit()
    
    def _read_config(self):
        """读取配置文件，如果不存在则返回默认配置"""
        default_config = {
            'base_font_size_px': 48, # 默认基础字体大小
            'voice_language': 'ja'
        }
        if os.path.exists(self.CONFIG_FILE):
            try:
                # In a real implementation, you'd use 'yaml.safe_load'
                # For this example, we assume it's read correctly or return default
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                   return yaml.safe_load(f)
                print("NOTE: YAML read function is a placeholder.")
                return default_config # Placeholder implementation
            except Exception as e:
                print(f"Error reading config file: {e}. Using default settings.")
                return default_config
        return default_config

    def _write_config(self):
        """将当前配置写入YAML文件"""
        try:
            # In a real implementation, you'd use 'yaml.dump'
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"Error writing config file: {e}")

def start_qt_app(display_queue, emotion_queue, deepseek):
    """启动PyQt应用"""
    app = QApplication(sys.argv)
    window = DesktopAssistantWindow(display_queue, emotion_queue, deepseek)
    print("QT Window starts!!")
    window.show()
    sys.exit(app.exec_())

import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import yaml
import time
from PyQt6.QtCore import QEvent, Qt, QThread, pyqtSignal, QObject, QSize, QUrl
from PyQt6.QtWidgets import QSlider
from PyQt6.QtGui import QFont, QImage, QPixmap, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QSizePolicy,
)
import os

from pathlib import Path

import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui import styles
from ui.components import CGWidget, ClickableLabel, TypingLabel, SpritePanel
from ui.desktop_menu import DesktopMenuMixin
from ui.desktop_toolbar import DesktopToolbarMixin
from ui.workers import ImageDisplayThread, ChatWorker
from ui.mic_button import MicButton
from config.config_manager import ConfigManager

config_manager = ConfigManager()

DIALOG_FRAME_PATH = Path('./assets/system/picture/dialog_frame.png').absolute().as_posix()
class DesktopAssistantWindow(DesktopToolbarMixin, DesktopMenuMixin, QWidget):
    """桌面助手主窗口"""
    message_submitted = pyqtSignal(str)  # 定义信号用于发送消息
    open_chat_history_dialog = pyqtSignal()  # 定义信号用于打开聊天历史记录对话框
    change_voice_language = pyqtSignal(str)  # 定义信号用于更改语音的语言
    close_window = pyqtSignal() #关闭窗口信号
    clear_chat_history = pyqtSignal()
    skip_speech_signal = pyqtSignal() # 跳过当前语音信号
    llm_reply_finished = pyqtSignal() # LLM 回复完成信号
    pause_asr_signal = pyqtSignal() # 暂停 ASR 信号
    copy_chat_history_to_clipboard = pyqtSignal() # 复制聊天记录到剪贴板信号.
    revert_chat_history = pyqtSignal(int) # 回溯聊天记录到指定索引

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
        self.current_background_path = None 

        self.base_font_size_px = config_manager.config.system_config.base_font_size_px

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
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
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

        # CG
        self.cg_widget = CGWidget(self.theme_color, self.image_container)
        self.cg_widget.cg_display_changed.connect(self.handle_cg_display_change)

        # 数值信息标签
        self.setup_numeric_label()

        # 立绘展示板
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
        self.cg_widget.lower() # 初始时，CG 在背景上方
        self.sprite_panel.raise_() # 立绘在 CG 上方
        self.dialog_label.raise_() # 对话框和选项在所有图像组件上方
        self.options_widget.raise_()

        self.setLayout(main_layout)

        self.cg_widget.setGeometry(0,0,self.original_width, self.original_height)
        self.apply_font_styles()
    
    def handle_cg_display_change(self, is_cg_visible: bool):
        """
        处理 CG 显示状态的改变。
        is_cg_visible: True 时隐藏立绘，False 时显示立绘。
        """
        if is_cg_visible:
            # 调整 CG 的层次，使其浮动到立绘之上，实现覆盖
            self.cg_widget.raise_()
            
            # 隐藏立绘
            self.sprite_panel.hide()
            
            # 确保对话框等元素在 CG 之上
            self.dialog_label.raise_() 
            self.options_widget.raise_()
            self.numeric_info_label.raise_()
            self.toolbar.raise_() 
            
        else:
            self.sprite_panel.show()
            # 恢复 CG 到立绘之下
            self.cg_widget.lower()
            self.cg_widget.hide()
    def show_cg_image(self, cg_path: str):
        """外部接口：显示一个CG，它会触发立绘隐藏"""
        self.cg_widget.show_cg(cg_path)
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
        
        self.dialog_label.setStyleSheet(
            styles.dialog_label_theme_applied(
                self.font_size, self.theme_color, self.second_color
            )
        )
        self.dialog_label.setPixmap(df_pixel_map)

        # Apply to numeric label
        self.numeric_info_label.setStyleSheet(
            styles.numeric_info_label_theme_applied(
                self.font_size,
                self.theme_color,
                self.second_color,
                QUrl.fromLocalFile(DIALOG_FRAME_PATH).toString(),
            )
        )

        # Apply to input box
        self.input_box.setStyleSheet(styles.text_edit_input(self.btn_font_size))

        # Apply to send button
        self.send_btn.setStyleSheet(
            styles.send_button_theme(self.theme_color, self.btn_font_size)
        )

        # Re-apply styles to any existing options (if visible/available)
        opt_refresh = styles.option_row_list_refresh(self.font_size)
        for i in range(self.options_layout.count()):
            item = self.options_layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                widget.setStyleSheet(opt_refresh)

        # Since sizes changed, force a re-layout/adjust
        self.dialog_label.adjustSize()
        self.numeric_info_label.adjustSize()
        if self.options_widget.isVisible():
            self.setDisplayWords("Test")
            self.setOptions(self.current_options)

    def setup_numeric_label(self):
        # 1. 创建用于显示富文本的“数值组件”
        self.numeric_info_label = QLabel(self.image_container) # 以 self.label (图像容器) 为父组件
        # 允许显示富文本（HTML 格式）
        self.numeric_info_label.setTextFormat(Qt.TextFormat.RichText) 
        # 设置初始文本（示例）
        self.numeric_info_label.setWordWrap(True)
        self.numeric_info_label.setText("<b>HP:</b> <span style='color:red;'>100</span>")
        
        # 3. 设置半透明背景和字体颜色
        # 为了覆盖图像，设置一个半透明背景，并确保文字清晰可见
        self.numeric_info_label.setStyleSheet(
            styles.numeric_info_label_initial(self.font_size)
        )
        
        # 4. 调整大小策略：根据内容自动调整
        self.numeric_info_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        # 5. 初始隐藏（如果需要，你也可以直接显示）
        self.numeric_info_label.hide() 

    def setup_dialog_label(self):
        """初始化对话框标签"""
        self.dialog_label = TypingLabel()
        self.dialog_label.clicked.connect(lambda: self.skip_speech_signal.emit()) 
        self.dialog_label.setTextFormat(Qt.TextFormat.RichText)
        self.dialog_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.dialog_label.setStyleSheet(
            styles.dialog_label_initial(self.font_size, DIALOG_FRAME_PATH)
        )
        self.dialog_label.setWordWrap(True)
        self.dialog_label.hide()
        self.dialog_label.setParent(self.image_container)

        self.skip_button = QPushButton(">")
        self.skip_button.setParent(self.image_container)
        self.skip_button.setFixedSize(48, 48)
        self.skip_button.setStyleSheet(styles.skip_speech_button())
        # 4. 连接按钮到跳过信号
        self.skip_button.hide()

    def setup_options_widget(self):
        """初始化选项容器，与对话框标签位置相同"""
        self.options_widget = QWidget()
        
        # 设置容器的基本样式，与dialog_label相似
        self.options_widget.setStyleSheet(styles.options_widget_container())
        
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
        # self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_layout.addWidget(self.sprite_panel)
    
    def setup_input_layout(self):
        """初始化输入布局"""
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        # 输入框
        self.input_box = QTextEdit()
        self.input_box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.input_box.setMaximumHeight(100)
        self.input_box.setPlaceholderText("输入消息...")
        self.input_box.setStyleSheet(styles.text_edit_input(self.btn_font_size))
        self.input_box.installEventFilter(self)
        # self.input_box.returnPressed.connect(self.sendMessage)
        
        # 发送按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(
            styles.send_button_input_bar_green(self.btn_font_size)
        )
        self.send_btn.clicked.connect(self.sendMessage)

        self.mic_button = MicButton(None)
        self.mic_button.set_input_widget(self.input_box)
        self.llm_reply_finished.connect(self.mic_button.resume_asr)
        self.pause_asr_signal.connect(self.mic_button.pause_asr)
        self.mic_button.send_final_transcription.connect(self.sendMessage)
        
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.mic_button)
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
        self.background_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.background_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        

    def setBackgroundImage(self, image_path: str):
        """
        设置窗口背景图片，图片将缩放填充整个窗口。
        
        :param image_path: 背景图片文件的路径。
        """
        if image_path == self.current_background_path:
            return
        self.sprite_panel.remove_all()  # 清除所有立绘显示
        if not os.path.exists(image_path):
            print(f"Background image file not found: {image_path}")
            # 可以设置一个纯色背景作为 fallback
            self.background_label.setStyleSheet(styles.background_label_load_failed())
            self.background_label.setText("背景图加载失败")
            return

        # 使用 QPixmap 加载图片
        pixmap = QPixmap(image_path)
        
        # 动态设置样式表，使用 border-image 来实现背景填充和缩放
        # 设置 background_label 的样式表
        # 使用 QPixmap + setPixmap；若改用纯 QSS 可试 styles.background_label_qlabel_image
        # 重新设置背景图片
        scaled_pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.background_label.setPixmap(scaled_pixmap)
        self.background_label.lower()
        self.current_background_path = image_path

    def update_image(self, image, character_name="", scale_rate=1.0):
        """更新显示图像"""
        self.original_image = image
        if image.size == 0:
            self.sprite_panel.remove(character_name)
        else:
             self.sprite_panel.switch_sprite(character_name, image, scale_rate)

    def sendMessage(self):
        """发送消息函数"""
        message = self.input_box.toPlainText().strip()
        if message:
            print(f"UI发送消息: {message}")
            self.input_box.clear()
            self.setDisplayWords(f"<b>你</b>：{message}")
            self.input_box.setPlaceholderText("发送成功喵，等待回复中……")
            self.mic_button.asr_pause_requested.emit()
            
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
            min_height = int(self.original_height * 0.3)
            max_height = int(self.original_height * 0.6)
            height = max(min_height, self.dialog_label.height())
            height = min(height, max_height)
            
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
            self.toolbar.raise_()
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
            option_btn.setTextFormat(Qt.TextFormat.RichText)
            option_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            option_btn.setWordWrap(True)
            
            # 设置半透明样式，使用主题色和字体大小
            option_btn.setStyleSheet(
                styles.option_choice_button(
                    self.font_size,
                    self.theme_color,
                    self.second_color,
                    low_opacity_theme,
                )
            )
            
            # 连接点击事件，使用 lambda 传递选项内容
            option_btn.clicked.connect(lambda text=option_text: self.option_clicked(text))
            self.options_layout.addWidget(option_btn)

        container_width = self.original_width # 使用 self.original_width 作为容器宽度
        margin_width = int(container_width * self.HORIZONTAL_MARGIN_PERCENT)
        new_width = container_width - (2 * margin_width)
        
        # 5a. 临时设置宽度来获取正确的 sizeHint (高度)
        self.options_widget.setFixedWidth(new_width)
        self.options_layout.activate()
        self.options_widget.adjustSize()
        
        # 5b. 获取适应新宽度后的高度
        final_height = self.options_widget.sizeHint().height()
        # 某些时机（如启动初期/回溯后）sizeHint 可能尚未稳定。
        # 使用当前字体度量估算每个选项文本所需高度，避免只显示一条缝或内容被截断。
        font = QFont('Microsoft YaHei')
        # self.font_size 形如 "32px;"，提取数字并设置给测量字体
        font_px = self.base_font_size_px
        try:
            font_px = int(self.font_size.replace("px", "").replace(";", "").strip())
        except Exception:
            pass
        font.setPixelSize(max(12, font_px))

        metrics = QFontMetrics(font)
        # 选项按钮可用文本宽度（扣掉左右边距和按钮 padding）
        text_width = max(120, new_width - 30 - 18)
        estimated_height = 15 + 15 + 10  # 容器上下边距 + 首个间距基线
        for option_text in optionList:
            rect = metrics.boundingRect(
                0, 0, text_width, 10000, int(Qt.TextFlag.TextWordWrap), option_text
            )
            # 按钮文本高度 + 按钮内边距 + 最小按钮高度 + 按钮间距
            option_height = max(40, rect.height() + 18)
            estimated_height += option_height + 10

        min_visible_height = max(80, estimated_height)
        final_height = max(final_height, min_visible_height)
        
        # 6. 放置在图像标签的底部
        y = self.original_height - final_height
        
        # 7. 设置居中的位置和最终的尺寸
        self.options_widget.setGeometry(margin_width, y, new_width, final_height)
        # 7. 显示选项
        self.options_widget.show()
        # 确保在图像和其他元素上方显示 (工具栏和对话框标签除外)
        self.options_widget.raise_()
        self.toolbar.raise_()

    def mousePressEvent(self, event):
        """实现窗口拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            g = event.globalPosition().toPoint()
            self.drag_position = g - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """拖动窗口"""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def closeEvent(self, event):
        """关闭窗口时停止线程"""
        self.mic_button.close()
        if self.display_thread:
            self.display_thread.stop()
            self.display_thread.wait()
        super().closeEvent(event)
        self.close_window.emit()

    def eventFilter(self, obj, event):
        if obj == self.input_box and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # 同样判断是否带有修饰键
                if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.send_btn.click() # 你的发送函数
                    return True # 表示事件已处理，不再向下传递（即不换行）
        return super().eventFilter(obj, event)

def start_qt_app(display_queue, emotion_queue, deepseek):
    """启动PyQt应用"""
    app = QApplication(sys.argv)
    window = DesktopAssistantWindow(display_queue, emotion_queue, deepseek)
    print("QT Window starts!!")
    window.show()
    sys.exit(app.exec())

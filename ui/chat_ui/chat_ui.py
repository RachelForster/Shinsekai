import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import yaml
import time
from PySide6.QtCore import QEvent, Qt, Signal, QSize, QUrl
from PySide6.QtGui import QFont, QImage, QPixmap, QFontMetrics, QShowEvent
from PySide6.QtWidgets import (
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

import logging
current_script = Path(__file__).resolve()
project_root = current_script.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ui.chat_ui import styles
from ui.chat_ui.components import CGWidget, ClickableLabel, TypingLabel, SpritePanel
from ui.chat_ui.desktop_menu import DesktopMenuMixin
from ui.chat_ui.desktop_toolbar import DesktopToolbarMixin
from ui.chat_ui.mic_button import MicButton
from ui.chat_ui.workers import ChatWorker, ImageDisplayThread
from config.config_manager import ConfigManager
from i18n import init_i18n, tr

config_manager = ConfigManager()

_logger = logging.getLogger(__name__)

DIALOG_FRAME_PATH = Path('./assets/system/picture/dialog_frame.png').absolute().as_posix()
class ChatUIWindow(DesktopToolbarMixin, DesktopMenuMixin, QWidget):
    """桌面助手主窗口"""
    message_submitted = Signal(str)  # 定义信号用于发送消息
    open_chat_history_dialog = Signal()  # 定义信号用于打开聊天历史记录对话框
    change_voice_language = Signal(str)  # 定义信号用于更改语音的语言
    close_window = Signal()  # 关闭窗口信号
    clear_chat_history = Signal()
    skip_speech_signal = Signal()  # 跳过当前语音信号
    llm_reply_finished = Signal()  # LLM 回复完成信号
    pause_asr_signal = Signal()  # 暂停 ASR 信号
    copy_chat_history_to_clipboard = Signal()  # 复制聊天记录到剪贴板信号.
    revert_chat_history = Signal(int)  # 回溯聊天记录到指定索引

    option_selected = Signal(str)
    llm_response_received = Signal(object)
    background_image_changed = Signal(str)
    notification_changed = Signal(str)
    display_words_changed = Signal(str)
    numeric_info_changed = Signal(str)

    # 聊天输入框 QTextEdit：获得 / 失去焦点（见 eventFilter）
    user_input_started = Signal()
    user_input_ended = Signal()

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
        # 全尺寸图，供 resize 时重缩放，使底栏 input 与整窗共用同一底图
        self._background_source_pixmap = None
        # 底栏叠在立绘上时，对话/选项需避开此高度（含底边留白，在 resize 中更新）
        self._bottom_chrome_h = 130
        # 底栏与窗口边距：左右内缩、距底边留白（与 _layout_input_row 一致）
        self._input_row_inset_h = 16
        self._input_row_inset_bottom = 10

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

        from ui.chat_ui.signal_bridge import attach_chat_ui_window

        attach_chat_ui_window(self)

    def setup_ui(self):
        """初始化UI组件"""
        # 窗口设置
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("DesktopAssistantWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 避免无边框+分层窗口在部分系统上出现非预期的灰边/默认底色渗出
        self.setStyleSheet(
            "#DesktopAssistantWindow { background: transparent; border: none; }"
        )
        
        # 主布局：立绘区独占整窗，底栏不占用 layout（叠在立绘上）
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
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
        
        # 底栏（叠在立绘上）
        self.setup_input_layout()
        
        # 将组件添加到主布局
        main_layout.addWidget(self.image_container, 1)
        
        self.background_label.lower()
        self.cg_widget.lower() # 初始时，CG 在背景上方
        self.sprite_panel.raise_() # 立绘在 CG 上方
        self.dialog_label.raise_() # 对话框和选项在所有图像组件上方
        self.options_widget.raise_()

        self.setLayout(main_layout)
        self._layout_input_row()
        self._raise_input_and_toolbar()

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
            self._raise_input_and_toolbar() 
            
        else:
            self.sprite_panel.show()
            # 恢复 CG 到立绘之下
            self.cg_widget.lower()
            self.cg_widget.hide()
            self._raise_input_and_toolbar()
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
        
        # 对话气泡只用 QSS 渐变，不要再叠一层 dialog_frame 位图，否则整图会随 QLabel
        # 拉伸，PNG 里画的装饰/灰边会看起来像「外圈多了一圈框」。
        self.dialog_label.setStyleSheet(
            styles.dialog_label_theme_applied(
                self.font_size, self.theme_color, self.second_color
            )
        )
        self.dialog_label.setPixmap(QPixmap())

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
        self.input_box.setPlaceholderText(tr("desktop.input_placeholder"))

        # Apply to send button
        self.send_btn.setText(tr("desktop.send"))
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
        self.image_layout.addWidget(self.sprite_panel, 1)
    
    def setup_input_layout(self):
        """初始化底栏；独立叠在窗口底部，使立绘区可铺满至窗口底边。"""
        self.input_row = QWidget(self)
        input_layout = QHBoxLayout(self.input_row)
        # 行内边距：与窗口边距（inset）配合，底栏不显得顶满
        input_layout.setContentsMargins(6, 5, 6, 6)
        input_layout.setSpacing(12)
        
        # 输入框
        self.input_box = QTextEdit()
        self.input_box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.input_box.setMinimumHeight(40)
        self.input_box.setMaximumHeight(80)
        self.input_box.setPlaceholderText(tr("desktop.input_placeholder"))
        self.input_box.setStyleSheet(styles.text_edit_input(self.btn_font_size))
        self.input_box.installEventFilter(self)
        # self.input_box.returnPressed.connect(self.sendMessage)
        
        # 发送按钮
        self.send_btn = QPushButton(tr("desktop.send"))
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

    def _layout_input_row(self) -> None:
        if getattr(self, "input_row", None) is None:
            return
        inset_h = self._input_row_inset_h
        inset_b = self._input_row_inset_bottom
        inner_w = max(1, int(self.width()) - 2 * inset_h)
        # 用足够高度量 sizeHint，避免行高被算小
        self.input_row.setGeometry(0, 0, inner_w, 200)
        self.input_row.updateGeometry()
        sh = int(self.input_row.sizeHint().height())
        # 行高：不低于麦克风按钮区（50）+ 内边距，不高于 ~125（约两行半 + 按钮）
        row_h = int(max(58, min(sh, 125)))
        y = int(self.height()) - row_h - inset_b
        x = inset_h
        self.input_row.setGeometry(x, max(0, y), inner_w, row_h)
        # 对话/选项要避开整段底栏 + 与窗口底边之间的留白
        self._bottom_chrome_h = row_h + inset_b

    def _above_chrome_y(self, block_height: int, gap: int = 4) -> int:
        h = int(self.image_container.height()) if self.image_container.height() > 0 else int(self.height())
        return max(0, h - self._bottom_chrome_h - gap - int(block_height))
    
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

    def _scale_and_apply_background(self) -> None:
        """将底图按当前窗口尺寸铺满（含底栏 input 区域）。"""
        if (
            self._background_source_pixmap is not None
            and not self._background_source_pixmap.isNull()
        ):
            scaled = self._background_source_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.background_label.setPixmap(scaled)
        self.background_label.setGeometry(0, 0, self.width(), self.height())
        self.background_label.lower()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not getattr(self, "_win_dwm_applied", False):
            self._win_dwm_applied = True
            from ui.win_frameless_dwm import apply_win_frameless_dwm_hacks

            apply_win_frameless_dwm_hacks(
                self, theme_color=getattr(self, "theme_color", None) or None
            )

    def _raise_input_and_toolbar(self) -> None:
        """将输入条与工具栏置于最前（相对各自父级叠放顺序）。"""
        if getattr(self, "input_row", None) is not None:
            self.input_row.raise_()
        else:
            if getattr(self, "input_box", None) is not None:
                self.input_box.raise_()
            if getattr(self, "mic_button", None) is not None:
                self.mic_button.raise_()
            if getattr(self, "send_btn", None) is not None:
                self.send_btn.raise_()
        if getattr(self, "toolbar", None) is not None:
            self.toolbar.raise_()
            w = self.image_container.width() if self.image_container.width() else self.width()
            self.toolbar.move(max(0, w - 200), 10)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_input_row()
        self.cg_widget.setGeometry(
            0,
            0,
            max(1, self.image_container.width()),
            max(1, self.image_container.height()),
        )
        self._scale_and_apply_background()
        self._raise_input_and_toolbar()

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
            self._background_source_pixmap = None
            # 可以设置一个纯色背景作为 fallback
            self.background_label.setStyleSheet(styles.background_label_load_failed())
            self.background_label.setText("背景图加载失败")
            self._raise_input_and_toolbar()
            return

        pixmap = QPixmap(image_path)
        self._background_source_pixmap = pixmap
        self.background_label.setText("")
        self.background_label.setStyleSheet("")
        self._scale_and_apply_background()
        self.current_background_path = image_path
        self.background_image_changed.emit(image_path)
        self._raise_input_and_toolbar()

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
            self.input_box.setPlaceholderText(tr("desktop.sending"))
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
            self._raise_input_and_toolbar()
        self.numeric_info_changed.emit(html_text)

    def setNotification(self, message):
        """设置提示词"""
        self.input_box.setPlaceholderText(message)
        self.notification_changed.emit(message)

    def handleResponse(self, result):
        """处理聊天响应"""
        if not self.sprite_mode:
            self.llm_response_received.emit(result)
            self.setDisplayWords(f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color: #A7CA90;'>狛枝凪斗</b>：{result['message']}</p>")
            if not self.emotion_queue.full():
                self.emotion_queue.put(result['emotion'])
            self.llm_reply_finished.emit()

    def setDisplayWords(self, text):
        """显示人物说的话"""
        if text:
            self.options_widget.hide()
            self.dialog_label.setText(text)
            container_width = self.image_container.width() or self.original_width
            margin_width = int(container_width * self.HORIZONTAL_MARGIN_PERCENT)
            new_width = container_width - (2 * margin_width)

            self.dialog_label.setFixedWidth(new_width)
            self.dialog_label.adjustSize()
            avail_h = max(1, (self.image_container.height() or self.height()) - self._bottom_chrome_h)
            min_height = int(avail_h * 0.3)
            max_height = int(avail_h * 0.6)
            height = max(min_height, self.dialog_label.height())
            height = min(height, max_height)
            
            # 2. 计算垂直位置：贴在底栏上方
            y = self._above_chrome_y(height, gap=4)
            
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
            self._raise_input_and_toolbar()
            self.display_words_changed.emit(text)
        else:
            self.dialog_label.hide()
            self.skip_button.hide() # 隐藏跳过按钮
            self.display_words_changed.emit("")
    
    def option_clicked(self, text):
        """选项按钮点击处理函数"""
        print(f"Option clicked: {text}")
        self.option_selected.emit(text)
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

        container_width = self.image_container.width() or self.original_width
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
        
        # 6. 贴在底栏上方
        y = self._above_chrome_y(final_height, gap=4)
        
        # 7. 设置居中的位置和最终的尺寸
        self.options_widget.setGeometry(margin_width, y, new_width, final_height)
        # 7. 显示选项
        self.options_widget.show()
        # 确保在图像和其他元素上方显示 (工具栏和对话框标签除外)
        self.options_widget.raise_()
        self._raise_input_and_toolbar()

    def mount_plugin_contributions(self, contributions: list) -> None:
        """
        Embed widgets from :mod:`sdk` plugins. ``placement`` hints:
        ``toolbar`` (left of existing actions), ``input_row`` (left of input),
        anything else: child of ``image_container`` (overlay).
        """
        if not contributions:
            return
        for c in sorted(contributions, key=lambda x: x.order):
            try:
                w = c.build(self)
            except Exception:
                _logger.exception("Desktop plugin widget failed: %s", c.widget_id)
                continue
            pl = (c.placement or "overlay").lower()
            if pl == "toolbar":
                tb = getattr(self, "toolbar", None)
                if tb is not None:
                    lay = tb.layout()
                    if lay is not None:
                        lay.insertWidget(0, w)
                        nw = max(200, lay.sizeHint().width() + 24)
                        cap = max(320, int(self.image_container.width() * 0.55))
                        tb.setFixedWidth(min(nw, cap))
                        x = max(0, self.image_container.width() - tb.width())
                        tb.move(x, 10)
            elif pl == "input_row":
                row = getattr(self, "input_row", None)
                if row is not None:
                    il = row.layout()
                    if il is not None:
                        il.insertWidget(0, w)
            else:
                w.setParent(self.image_container)
                w.show()
            self._raise_input_and_toolbar()

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
        from ui.chat_ui.signal_bridge import detach_chat_ui_window

        detach_chat_ui_window()

    def eventFilter(self, obj, event):
        if obj == self.input_box:
            et = event.type()
            if et == QEvent.Type.FocusIn:
                self.user_input_started.emit()
            elif et == QEvent.Type.FocusOut:
                self.user_input_ended.emit()
            elif et == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    # 同样判断是否带有修饰键
                    if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self.send_btn.click()  # 你的发送函数
                        return True  # 表示事件已处理，不再向下传递（即不换行）
        return super().eventFilter(obj, event)

def start_qt_app(display_queue, emotion_queue, deepseek):
    """启动 PySide6 应用（ChatUI）。"""
    init_i18n(config_manager.config.system_config.ui_language)
    app = QApplication(sys.argv)
    window = ChatUIWindow(display_queue, emotion_queue, deepseek)
    print("ChatUI (PySide6) window starts")
    window.show()
    sys.exit(app.exec())

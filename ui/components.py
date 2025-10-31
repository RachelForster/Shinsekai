import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import pygame
import yaml
import time
from PyQt5.QtCore import QEasingCurve, QRect, QTimer, Qt, QThread, pyqtSignal, QObject, QSize, QPropertyAnimation, QSequentialAnimationGroup, pyqtProperty
from PyQt5.QtWidgets import QGraphicsColorizeEffect, QGridLayout, QSlider
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, QMenu, QAction,QDialog, QListWidget, QListWidgetItem, QButtonGroup, QRadioButton, QGraphicsOpacityEffect,
                             QHBoxLayout, QPushButton, QLineEdit, QSizePolicy)
import os

from PyQt5.QtGui import QImage, QPixmap


# 交叉渐变立绘组件
# 交叉渐变立绘组件
class CrossFadeSprite(QWidget):
    def __init__(self, original_width, original_height, parent=None):
        super().__init__(parent)
        # 从外部获取原始宽高，用于缩放计算
        self.original_width = original_width
        self.original_height = original_height 
        self.setFixedSize(original_width, original_height)
        self.current_character: str | None = None  # 当前显示的角色名
        
        # 布局，确保两个 QLabel 重叠
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0) # 确保没有间距 
        
        # --- 两个重叠的 QLabel ---
        
        # 1. '旧' 立绘标签 - 用于淡出
        self.label_old = QLabel(self)
        self.label_old.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.label_old.setScaledContents(False) 
        self.old_opacity_effect = QGraphicsOpacityEffect(self.label_old)
        self.old_opacity_effect.setOpacity(1.0)
        self.label_old.setGraphicsEffect(self.old_opacity_effect)
        
        # 2. '新' 立绘标签 - 用于淡入
        self.label_new = QLabel(self)
        self.label_new.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.label_new.setScaledContents(False)
        self.new_opacity_effect = QGraphicsOpacityEffect(self.label_new)
        self.new_opacity_effect.setOpacity(0.0)
        self.label_new.setGraphicsEffect(self.new_opacity_effect)
        
        # 将两个 QLabel 都添加到布局中（它们会自动重叠）
        layout.addWidget(self.label_old, 0, 0)
        layout.addWidget(self.label_new, 0, 0)
        
        # 动画和状态
        self.fade_duration = 300  # 渐变持续时间 (毫秒)
        self.is_animating = False

    def _get_scaled_pixmap(self, image: np.ndarray, character_rate=None) -> QPixmap:
        """
        将 numpy 图像转换为缩放后的 QPixmap。
        """
        # 1. 转换为 QImage/QPixmap
        height, width, channel = image.shape
        # bytes_per_line = 4 * width # 假设输入图像是 RGBA8888 格式
        # PyQt5 中，QImage 构造函数可以直接处理 buffer，但如果使用 fromBuffer，
        # 需要确保数据类型和步长正确。此处我们沿用您提供的 QImage(data, w, h, bpl, format) 构造
        bytes_per_line = width * channel  # 实际的字节数，4*width 仅适用于 RGBA8888
        
        # 确保格式匹配：如果您的 np 数组是 4 通道 (RGBA)，请使用 QImage.Format_RGBA8888
        qimg = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        
        # 2. 缩放逻辑
        max_width = self.original_width - 20
        max_height = self.original_height * 0.9
        
        img_width = pixmap.width()
        img_height = pixmap.height()
        
        rate_x = max_width / img_width if img_width > 0 else 0
        rate_y = max_height / img_height if img_height > 0 else 0

        # rate = min(rate_x, rate_y) * (1 if character_rate is None else character_rate)
        rate = rate_y * (1 if character_rate is None else character_rate)

        if rate <= 0: return QPixmap()

        # 应用缩放
        scaled_pixmap = pixmap.scaled(
            int(img_width * rate), 
            int(img_height * rate),
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        return scaled_pixmap

    def setSprite(self, image: np.ndarray, character_rate=None):
        """
        加载新立绘并开始交叉渐变动画。
        """
        if self.is_animating:
            print("正在进行动画，忽略本次切换。")
            return
            
        scaled_pixmap = self._get_scaled_pixmap(image, character_rate)
        if scaled_pixmap.isNull():
            print("错误：无法生成有效的 QPixmap。")
            return
            
        # 1. 将新立绘设置到 '新' 标签上
        self.label_new.setPixmap(scaled_pixmap)
        self.is_animating = True
        
        # --- 创建动画 ---
        
        # 动画 1: 旧立绘淡出 (1.0 -> 0.0)
        anim_fade_out = QPropertyAnimation(self.old_opacity_effect, b"opacity")
        anim_fade_out.setDuration(self.fade_duration)
        anim_fade_out.setStartValue(1.0)
        anim_fade_out.setEndValue(0.0)
        
        # 动画 2: 新立绘淡入 (0.0 -> 1.0)
        anim_fade_in = QPropertyAnimation(self.new_opacity_effect, b"opacity")
        anim_fade_in.setDuration(self.fade_duration)
        anim_fade_in.setStartValue(0.0)
        anim_fade_in.setEndValue(1.0)

        # QSequentialAnimationGroup 用于同时播放两个动画
        self.parallel_group = QSequentialAnimationGroup(self)
        self.parallel_group.addAnimation(anim_fade_out)
        self.parallel_group.addAnimation(anim_fade_in)
        
        self.parallel_group.finished.connect(self._animationFinished)
        
        # 开始动画
        self.parallel_group.start()
        self.resize(scaled_pixmap.width(), self.height())
        return scaled_pixmap.width(), self.height()

    def _animationFinished(self):
        """动画结束后的清理工作"""
        # 1. 将 '新' 标签的 Pixmap 转移到 '旧' 标签
        current_pixmap = self.label_new.pixmap()
        if current_pixmap:
            self.label_old.setPixmap(current_pixmap.copy()) # 使用 copy 确保数据独立性
        
        # 2. 重置 '旧' 标签的透明度为 1.0 
        self.old_opacity_effect.setOpacity(1.0)
        
        # 3. 清空 '新' 标签的 Pixmap 并重置透明度为 0.0
        self.label_new.clear()
        self.new_opacity_effect.setOpacity(0.0)
        
        self.is_animating = False

    def setInitialSprite(self, image: np.ndarray, character_rate=None):
        """用于程序启动时第一次设置立绘，不带动画。"""
        scaled_pixmap = self._get_scaled_pixmap(image, character_rate)
        if scaled_pixmap:
            self.label_old.setPixmap(scaled_pixmap)
    
    def clear(self):
        """清除立绘"""
        self.label_old.clear()
        self.label_new.clear()
        self.current_character = None

class SpritePanel(QWidget):
    """
    立绘显示面板，使用绝对定位实现立绘重叠和居中错位。
    立绘尺寸采用固定高度、自由宽度策略。
    """
    def __init__(self, panel_width: int, panel_height: int, max_slots_num: int = 3, parent=None):
        super().__init__(parent)
        self.panel_width = panel_width
        self.panel_height = panel_height
        self.setFixedSize(panel_width, panel_height)
        self.max_slots_num = max_slots_num
        
        # 尺寸参考 (用于 CrossFadeSprite 内部缩放高度)
        self.sprite_width_ref = panel_width  # 宽度只做参考，不限制
        self.sprite_height_ref = panel_height
        
        # --- 布局 (使用 QHBoxLayout 仅实现居中) ---
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 关键：center_widget 是立绘的父容器，用于绝对定位
        self.center_widget = QWidget(self)
        # center_widget 的尺寸应与 SpritePanel 相同，以便正确计算绝对坐标
        self.center_widget.setFixedSize(panel_width, panel_height) 
        
        # 将 center_widget 居中
        self.main_layout.addStretch(1)
        self.main_layout.addWidget(self.center_widget)
        self.main_layout.addStretch(1)

        # --- 槽位管理 ---
        self.sprite_slots = []
        self.sprite_lru = {}  # {character_id: slot_index}
        
        # 计算水平偏移量 (用于错开立绘)
        # 将面板宽度分成 N+1 份，中心点落在第 1, 2, ..., N 份的交界处
        self.horizontal_offset_unit = self.panel_width / self.max_slots_num
        
        # 初始化槽位
        for i in range(self.max_slots_num):
            # 将 center_widget 作为父对象
            sprite = CrossFadeSprite(self.sprite_width_ref, self.sprite_height_ref, self.center_widget)
            
            # 初始尺寸：设为 0，等待 set_sprite 时调整
            sprite.setGeometry(0, 0, 0, 0)
            
            self.sprite_slots.append(sprite)
            sprite.hide()

    def _get_or_create_slot(self, character_id: str) -> CrossFadeSprite | None:
        """
        获取或创建立绘槽位。
        """
        if character_id in self.sprite_lru:
            # 命中，更新 LRU
            slot_index = self.sprite_lru.pop(character_id)
            self.sprite_lru[character_id] = slot_index
            return self.sprite_slots[slot_index]

        # 未命中，分配新槽位
        if len(self.sprite_lru) < self.max_slots_num:
            # 还有空闲槽位，从最小索引开始找
            used_indices = set(self.sprite_lru.values())
            for i in range(self.max_slots_num):
                if i not in used_indices:
                    slot_index = i
                    break
        else:
            # LRU淘汰
            oldest_id, slot_index = next(iter(self.sprite_lru.items()))
            self.sprite_lru.pop(oldest_id)
            self.sprite_slots[slot_index].clear() # 清理被淘汰槽位

        self.sprite_lru[character_id] = slot_index
        return self.sprite_slots[slot_index]
    def _reposition_sprites(self):
        """
        重新计算并定位所有可见立绘，确保立绘组在 SpritePanel 中居中。
        """
        active_slots = []
        for char_id, slot_index in self.sprite_lru.items():
            sprite = self.sprite_slots[slot_index]
            # 获取当前立绘的实际宽度
            w = sprite.width()
            if w > 0:
                active_slots.append({'sprite': sprite, 'index': slot_index, 'w': w})

        if not active_slots:
            return

        # 1. 估算立绘组的最小/最大 X 坐标 (基于目标中心点)
        min_slot_index = min(s['index'] for s in active_slots)
        max_slot_index = max(s['index'] for s in active_slots)
        
        # 目标中心点的 X 坐标范围：从 (min_slot_index + 1) 到 (max_slot_index + 1) * offset_unit
        
        # 计算最左侧立绘的左边缘 X_min
        # X_min = 目标中心点 X[min_slot] - 0.5 * w[min_slot]
        target_center_min = self.horizontal_offset_unit * (min_slot_index + 1)
        X_min = target_center_min - (active_slots[0]['w'] / 2) # 假设第一个就是 min_slot 的立绘

        # 计算最右侧立绘的右边缘 X_max
        # X_max = 目标中心点 X[max_slot] + 0.5 * w[max_slot]
        target_center_max = self.horizontal_offset_unit * (max_slot_index + 1)
        X_max = target_center_max + (active_slots[-1]['w'] / 2) # 假设最后一个就是 max_slot 的立绘
       
        group_width = target_center_max - target_center_min + (active_slots[-1]['w'] / 2) + (active_slots[0]['w'] / 2) # 估算组宽度
        
        # 整体居中补偿 (将立绘组中心对齐到面板中心)
        # compensation = (self.panel_width / 2) - (target_center_min + target_center_max) / 2
        compensation = (self.panel_width / 2) - ((target_center_min + target_center_max) / 2) # 居中补偿
        
        # 重新定位所有立绘
        for item in active_slots:
            w = item['w']
            sprite = item['sprite']
            slot_index = item['index']
            
            # 目标中心点 X 坐标
            target_center_x = self.horizontal_offset_unit * (slot_index + 1) 
            
            # 实际左上角 X 坐标 (居中对齐) + 整体补偿
            x_pos = target_center_x - (w / 2) + compensation
            
            # Y 坐标 (底部对齐)
            y_pos = self.panel_height - sprite.height() # 使用 sprite.height()，因为它被 resize 过了

            sprite.move(int(x_pos), int(y_pos))

    def switch_sprite(self, character_id: str, image_data: np.ndarray, character_rate=None):
        """
        设置立绘并显示，动态调整其位置和尺寸。
        """
        sprite = self._get_or_create_slot(character_id)
        if sprite is None: return

        # 1. 设置立绘并获取实际的缩放尺寸
        w, h = sprite.setSprite(image_data, character_rate)

        if w == 0 or h == 0: return

        # 2. 重新计算立绘位置 (居中对齐到槽位中心点)
        slot_index = self.sprite_lru[character_id]
        
        # 目标中心点 X 坐标 (在 center_widget 内的绝对坐标)
        target_center_x = self.horizontal_offset_unit * (slot_index)

        # 实际左上角 X 坐标 (实现立绘在其槽位中心居中)
        x_pos = target_center_x - (w / 2) 
        
        # Y 坐标 (底部对齐)
        y_pos = 0
        
        # 3. 应用新的位置和尺寸
        sprite.setGeometry(int(x_pos), int(y_pos), int(w), int(h))
        
        self._reposition_sprites()
        # 4. 显示和层级
        sprite.show()
        sprite.raise_() # 确保新登场或切换的立绘在最前面


    def darken_all(self, exclude_character_id: str | None = None):
        """
        使所有非当前说话者的立绘变暗。
        """
        for char_id, slot_index in self.sprite_lru.items():
            sprite = self.sprite_slots[slot_index]
            if char_id == exclude_character_id:
                # sprite.lighten()
                sprite.raise_() # 确保说话者在最前面
            # else:
                # sprite.darken()

    def clear_all(self):
        """
        清除所有立绘。
        """
        for sprite in self.sprite_slots:
            sprite.clear()
        self.sprite_lru.clear()

class FontSizeDialog(QDialog):
    """用于设置字体大小的对话框"""
    def __init__(self, current_base_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置字体大小")
        self.setModal(True)
        self.current_base_size = current_base_size
        self.new_base_size = current_base_size

        self.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 200);
                border-radius: 10px;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 16px;
                padding: 5px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #505050;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #4CAF50;
                border: 1px solid #ddd;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
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
        """)

        self.init_ui()
        self.adjustSize()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # 标签
        info_label = QLabel("调整UI文本基础大小（影响对话和按钮）：")
        layout.addWidget(info_label)

        # 滑块
        self.slider = QSlider(Qt.Horizontal)
        # 假设最小基础字体为10px，最大为60px
        self.slider.setRange(10, 60) 
        # 初始值是当前的基础字体大小
        self.slider.setValue(self.current_base_size) 
        self.slider.setSingleStep(2)
        self.slider.valueChanged.connect(self.update_label)
        layout.addWidget(self.slider)

        # 当前值显示标签
        self.value_label = QLabel(f"当前大小: {self.current_base_size}px")
        layout.addWidget(self.value_label)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.confirm_button = QPushButton("确定")
        self.confirm_button.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_button)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(200, 50, 50, 200);
            }
            QPushButton:hover {
                background-color: rgba(200, 50, 50, 255);
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def update_label(self, value):
        self.new_base_size = value
        self.value_label.setText(f"当前大小: {value}px")

    def get_new_font_size(self):
        return self.new_base_size

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

class ClickableLabel(QLabel):
    """可点击的标签"""
    clicked = pyqtSignal()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # 播放短音效使用 pygame.mixer.Sound，而不是 pygame.mixer.music
            self.click_sound = pygame.mixer.Sound('./assets/system/sound/switch.ogg')
        except Exception as e:
            print(f"Error loading sound effect: {e}")
            self.click_sound = None

    def play_click_sound(self):
        """播放点击音效"""
        if self.click_sound:
            # 使用 .play() 播放音效
            self.click_sound.play()

    def mousePressEvent(self, event):
        self.clicked.emit()
        self.play_click_sound()

class TypingLabel(ClickableLabel):
    typingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 打字机相关属性
        self._full_text = ""      # 要完整显示的文本
        self._current_char_index = 0 # 当前显示到第几个字符
        self._is_typing = False
        
        # QTimer 用于驱动逐字显示
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self._type_next_character)
        self.typing_delay = 50 # 字符之间的毫秒间隔 (可调整)
        
        # 连接跳过按钮到打字机逻辑
        self.clicked.connect(self.skip_typing)

    # ----------------------------------------------------------------------
    # 实现打字机效果
    # ----------------------------------------------------------------------

    def setDisplayWords(self, text: str):
        """
        开始逐字显示文本。
        """
        if not text:
            self.hide()
            return

        # 1. 初始化打字状态
        if self._is_typing:
            self.typing_timer.stop() # 如果正在打字，先停止
        
        self._full_text = text
        self._current_char_index = text.find('：')  # 从名字后开始打字
        self._is_typing = True

        self.setText(text[:self._current_char_index])
        
        # 5. 启动打字机
        self.typing_timer.start(self.typing_delay)


    def _type_next_character(self):
        """
        QTimer 触发时调用的槽函数，显示下一个字符。
        """
        if self._current_char_index < len(self._full_text):
            # 获取当前已显示的文本
            current_text = self._full_text[:self._current_char_index + 1]
            self.setText(current_text)
            self._current_char_index += 1
        else:
            # 文本显示完毕
            self.typing_timer.stop()
            self._is_typing = False
            self.typingFinished.emit() # 发出完成信号
            print("打字完成。")

    def skip_typing(self):
        """
        立即显示全部文本并停止打字机。
        """
        if self._is_typing:
            self.typing_timer.stop()
            self.setText(self._full_text)
            self._is_typing = False
            self.typingFinished.emit()
            print("打字被跳过。")
            
    # 重新实现 ClickableLabel 基类的内部跳过方法，防止重复连接或冲突
    def _skip_typing_internal(self):
        self.skip_typing()

    def mousePressEvent(self, event):
        """
        点击事件：如果正在打字，则跳过；否则，传递给基类。
        """
        if self._is_typing:
            self.skip_typing()
        else:
            super().mousePressEvent(event) # 传递给 ClickableLabel 的点击处理
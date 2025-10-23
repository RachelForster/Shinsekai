import sys
from PIL.ImageChops import screen
import numpy as np
import threading
import pygame
import yaml
import time
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QSize
from PyQt5.QtWidgets import QSlider
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, QMenu, QAction,QDialog, QListWidget, QListWidgetItem, QButtonGroup, QRadioButton,
                             QHBoxLayout, QPushButton, QLineEdit, QSizePolicy)
import os

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
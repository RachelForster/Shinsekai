"""主窗口设置菜单（历史、字体、语言、音量、主题等）。"""

from __future__ import annotations

import pygame
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from config.config_manager import ConfigManager
from ui.chat_ui.components import (
    FontSizeDialog,
    LanguageDialog,
    MessageDialog,
    ThemeColorDialog,
    VolumeDialog,
)

config_manager = ConfigManager()


class DesktopMenuMixin:
    def show_font_size_settings(self) -> None:
        """显示字体大小设置对话框"""
        dialog = FontSizeDialog(self.base_font_size_px, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_size = dialog.get_new_font_size()
            if new_size != self.base_font_size_px:
                self.base_font_size_px = new_size
                config_manager.config.system_config.base_font_size_px = new_size
                config_manager.save_system_config()
                self.apply_font_styles()
                self.setNotification(f"字体大小已更改为 {new_size}px")

    def show_settings_menu(self) -> None:
        """显示设置下拉菜单"""
        menu = QMenu(self)

        history_action = QAction("历史记录", self)
        clear_history_action = QAction("清空历史记录", self)
        copy_history_action = QAction("复制历史记录到剪贴板", self)
        language_action = QAction("语音语言", self)
        font_size_action = QAction("字体大小", self)
        volumn_action = QAction("音量", self)
        theme_color_action = QAction("主题色", self)

        history_action.triggered.connect(lambda: self.open_chat_history_dialog.emit())
        language_action.triggered.connect(self.show_language_settings)
        clear_history_action.triggered.connect(self.clear_history)
        font_size_action.triggered.connect(self.show_font_size_settings)
        volumn_action.triggered.connect(self.show_volumn_settings)
        theme_color_action.triggered.connect(self.show_theme_color_dialog)
        copy_history_action.triggered.connect(self.copy_chat_history_to_clipboard)

        menu.addAction(history_action)
        menu.addAction(clear_history_action)
        menu.addAction(copy_history_action)
        menu.addAction(language_action)
        menu.addAction(font_size_action)
        menu.addAction(volumn_action)
        menu.addAction(theme_color_action)

        menu.exec(
            self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft())
        )

    def show_volumn_settings(self) -> None:
        dialog = VolumeDialog(config_manager.config.system_config.music_volumn)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_volumn = dialog.get_new_volume()
            config_manager.config.system_config.music_volumn = selected_volumn
            config_manager.save_system_config()
            pygame.mixer.music.set_volume(selected_volumn / 100)

    def clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认",
            "您确定要清除历史吗？。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_chat_history.emit()

    def open_history_dialog(self, messages) -> None:
        dialog = MessageDialog(messages, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_revert_user_index is not None:
            self.revert_chat_history.emit(dialog.selected_revert_user_index)

    def show_theme_color_dialog(self) -> None:
        dialog = ThemeColorDialog(self.theme_color)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.theme_color = dialog.get_selected_color()
            config_manager.config.system_config.theme_color = self.theme_color
            self.apply_font_styles()
            self.setNotification("主题颜色已更改" + self.theme_color)
            config_manager.save_system_config()

    def show_language_settings(self) -> None:
        """显示语音语言设置"""
        dialog = LanguageDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
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

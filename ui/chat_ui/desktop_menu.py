"""主窗口设置菜单（历史、字体、语言、音量、主题等）。"""

from __future__ import annotations

import pygame
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from config.config_manager import ConfigManager
from i18n import tr
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
                self.setNotification(tr("desktop.menu.notify_font_size", size=new_size))

    def show_settings_menu(self) -> None:
        """显示设置下拉菜单"""
        menu = QMenu(self)

        history_action = QAction(tr("desktop.menu.history"), self)
        clear_history_action = QAction(tr("desktop.menu.clear_history"), self)
        copy_history_action = QAction(tr("desktop.menu.copy_history"), self)
        language_action = QAction(tr("desktop.menu.voice_language"), self)
        font_size_action = QAction(tr("desktop.menu.font_size"), self)
        volumn_action = QAction(tr("desktop.menu.volume"), self)
        theme_color_action = QAction(tr("desktop.menu.theme_color"), self)
        pin_top_action = QAction(tr("desktop.menu.pin_top"), self)
        pin_top_action.setCheckable(True)
        pin_top_action.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))

        history_action.triggered.connect(lambda: self.open_chat_history_dialog.emit())
        language_action.triggered.connect(self.show_language_settings)
        clear_history_action.triggered.connect(self.clear_history)
        font_size_action.triggered.connect(self.show_font_size_settings)
        volumn_action.triggered.connect(self.show_volumn_settings)
        theme_color_action.triggered.connect(self.show_theme_color_dialog)
        copy_history_action.triggered.connect(self.copy_chat_history_to_clipboard)
        pin_top_action.triggered.connect(self._toggle_pin_top)

        menu.addAction(history_action)
        menu.addAction(clear_history_action)
        menu.addAction(copy_history_action)
        menu.addAction(language_action)
        menu.addAction(font_size_action)
        menu.addAction(volumn_action)
        menu.addAction(theme_color_action)
        drawing_menu = menu.addMenu(tr("desktop.menu.drawing_engine"))
        drawing_group = QActionGroup(self)
        drawing_group.setExclusive(True)
        current_t2i = (
            str(config_manager.config.api_config.t2i_provider or "").strip().lower()
        )
        local_drawing_action = QAction(tr("desktop.menu.drawing_local"), self)
        api_drawing_action = QAction(tr("desktop.menu.drawing_api"), self)
        for action in (local_drawing_action, api_drawing_action):
            action.setCheckable(True)
            drawing_group.addAction(action)
            drawing_menu.addAction(action)
        local_drawing_action.setChecked(current_t2i in ("comfyui", "local"))
        api_drawing_action.setChecked(current_t2i in ("openai-image", "newapi-image", "api"))
        local_drawing_action.triggered.connect(
            lambda _checked=False: self._switch_drawing_provider("local")
        )
        api_drawing_action.triggered.connect(
            lambda _checked=False: self._switch_drawing_provider("api")
        )
        menu.addSeparator()
        menu.addAction(pin_top_action)

        menu.exec(
            self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft())
        )

    def show_volumn_settings(self) -> None:
        dialog = VolumeDialog(
            config_manager.config.system_config.music_volumn, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_volumn = dialog.get_new_volume()
            config_manager.config.system_config.music_volumn = selected_volumn
            config_manager.save_system_config()
            pygame.mixer.music.set_volume(selected_volumn / 100)

    def _toggle_pin_top(self, checked: bool) -> None:
        """切换窗口置顶状态。"""
        if checked:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()  # 改 flags 后必须 show 才能生效

    def _switch_drawing_provider(self, provider: str) -> None:
        """切换绘画后端，并尽量让当前会话立刻生效。"""
        try:
            from core.runtime.app_runtime import try_get_app_runtime
            from t2i.provider_switcher import switch_t2i_provider
            from t2i.t2i_manager import T2IAdapterFactory, T2IManager

            canonical = switch_t2i_provider(provider)
            config_manager._load_all_configs()
            api = config_manager.config.api_config
            base_kwargs = {
                "work_path": api.t2i_work_path,
                "api_url": api.t2i_api_url,
                "workflow_path": api.t2i_default_workflow_path,
                "prompt_node_id": api.t2i_prompt_node_id,
                "output_node_id": api.t2i_output_node_id,
            }
            adapter = T2IAdapterFactory.create_adapter(
                adapter_name=api.t2i_provider,
                **config_manager.merged_t2i_factory_kwargs(
                    api.t2i_provider, base_kwargs
                ),
            )
            rt = try_get_app_runtime()
            if rt is not None:
                if rt.t2i_manager is None:
                    rt.t2i_manager = T2IManager(adapter)
                else:
                    rt.t2i_manager.set_t2i_adapter(adapter)
            label_key = (
                "desktop.menu.drawing_local"
                if canonical == "comfyui"
                else "desktop.menu.drawing_api"
            )
            self.setNotification(
                tr(
                    "desktop.menu.notify_drawing_engine",
                    engine=tr(label_key),
                )
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.drawing_switch_failed_title"),
                tr("desktop.menu.drawing_switch_failed_body", error=str(e)),
            )

    def clear_history(self) -> None:
        reply = QMessageBox.question(
            self,
            tr("desktop.menu.confirm_clear_title"),
            tr("desktop.menu.confirm_clear_body"),
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
        # 主窗带 WindowStaysOnTopHint；无 parent 的对话框会叠在主窗后面
        dialog = ThemeColorDialog(self.theme_color, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.theme_color = dialog.get_selected_color()
            config_manager.config.system_config.theme_color = self.theme_color
            self.apply_font_styles()
            self.setNotification(
                tr("desktop.menu.notify_theme_color", color=self.theme_color)
            )
            config_manager.save_system_config()

    def show_language_settings(self) -> None:
        """显示语音语言设置"""
        dialog = LanguageDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_language = dialog.get_selected_language()
            print(f"选择的语言: {selected_language}")
            self.change_voice_language.emit(selected_language)
            voice_labels = {
                "en": "template.voice_lang_en",
                "zh": "template.voice_lang_zh",
                "ja": "template.voice_lang_ja",
                "yue": "template.voice_lang_yue",
            }
            language_str = tr(voice_labels.get(selected_language, "template.voice_lang_en"))

            config_manager.config.system_config.voice_language = selected_language
            config_manager.save_system_config()
            self.setNotification(
                tr("desktop.menu.notify_voice_language", lang=language_str)
            )

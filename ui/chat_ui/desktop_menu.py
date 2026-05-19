"""主窗口设置菜单（历史、字体、语言、音量、主题等）。"""

from __future__ import annotations

import copy

import pygame
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
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
from ui.chat_ui.save_slot_dialog import SaveSlotDialog

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
        save_slot_action = QAction(tr("desktop.menu.save_slot_save"), self)
        load_slot_action = QAction(tr("desktop.menu.save_slot_load"), self)
        load_auto_slot_action = QAction(tr("desktop.menu.save_slot_load_auto"), self)
        language_action = QAction(tr("desktop.menu.voice_language"), self)
        font_size_action = QAction(tr("desktop.menu.font_size"), self)
        volumn_action = QAction(tr("desktop.menu.volume"), self)
        theme_color_action = QAction(tr("desktop.menu.theme_color"), self)
        pin_top_action = QAction(tr("desktop.menu.pin_top"), self)
        pin_top_action.setCheckable(True)
        pin_top_action.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))

        history_action.triggered.connect(lambda: self.open_chat_history_dialog.emit())
        save_slot_action.triggered.connect(self._open_save_slot_dialog)
        load_slot_action.triggered.connect(self._open_load_slot_dialog)
        load_auto_slot_action.triggered.connect(self._load_auto_save_slot)
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
        save_slots_menu = menu.addMenu(tr("desktop.menu.save_slots"))
        save_slots_menu.addAction(save_slot_action)
        save_slots_menu.addAction(load_slot_action)
        try:
            from core.sprite.save_slots import get_auto_slot_summary

            load_auto_slot_action.setEnabled(get_auto_slot_summary().exists)
        except Exception:
            load_auto_slot_action.setEnabled(False)
        save_slots_menu.addAction(load_auto_slot_action)
        menu.addAction(language_action)
        menu.addAction(font_size_action)
        menu.addAction(volumn_action)
        menu.addAction(theme_color_action)
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

    def _session_messages_for_save(self) -> list:
        try:
            from core.runtime.app_runtime import try_get_app_runtime

            rt = try_get_app_runtime()
            manager = rt.llm_manager if rt is not None else None
        except Exception:
            manager = None
        if manager is None:
            manager = getattr(self, "deepseek", None)
        if manager is None:
            return []
        try:
            if hasattr(manager, "_strip_orphaned_tool_calls"):
                manager._strip_orphaned_tool_calls()
        except Exception:
            pass
        try:
            return list(manager.get_messages())
        except Exception:
            return []

    def _session_bgm_path_for_save(self) -> str:
        try:
            from core.runtime.app_runtime import try_get_app_runtime

            rt = try_get_app_runtime()
            if rt is not None and rt.ui_update_manager is not None:
                return str(rt.ui_update_manager.current_bgm_path or "")
        except Exception:
            pass
        return ""

    def _open_save_slot_dialog(self) -> None:
        try:
            from core.sprite.save_slots import list_manual_slots, save_slot

            slots = list_manual_slots()
            dialog = SaveSlotDialog(mode="save", slots=slots, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            slot_id = dialog.selected_slot_id
            summary = next((slot for slot in slots if slot.slot_id == slot_id), None)
            if summary is not None and summary.exists:
                reply = QMessageBox.question(
                    self,
                    tr("desktop.menu.save_slot_overwrite_title"),
                    tr("desktop.menu.save_slot_overwrite_body", slot=summary.label),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            saved = save_slot(
                slot_id,
                self._session_messages_for_save(),
                background_path=getattr(self, "current_background_path", "") or "",
                bgm_path=self._session_bgm_path_for_save(),
                history_file=getattr(self, "current_history_file", "") or "",
            )
            self.setNotification(
                tr("desktop.menu.save_slot_saved", slot=saved.label)
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.save_slot_failed_title"),
                tr("desktop.menu.save_slot_failed_body", error=str(e)),
            )

    def _open_load_slot_dialog(self) -> None:
        try:
            from core.sprite.save_slots import list_manual_slots

            dialog = SaveSlotDialog(
                mode="load", slots=list_manual_slots(), parent=self
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._load_save_slot(dialog.selected_slot_id)
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.save_slot_load_failed_title"),
                tr("desktop.menu.save_slot_load_failed_body", error=str(e)),
            )

    def _load_auto_save_slot(self) -> None:
        self._load_save_slot("auto")

    def _load_save_slot(self, slot_id: str) -> None:
        try:
            from core.runtime.app_runtime import try_get_app_runtime
            from core.sprite.chat_history import (
                chat_history,
                rebuild_chat_history,
                replay_history_entry,
            )
            from core.sprite.save_slots import last_user_text, load_slot, slot_label
            from sdk.messages import TTSOutputMessage

            reply = QMessageBox.question(
                self,
                tr("desktop.menu.save_slot_confirm_load_title"),
                tr("desktop.menu.save_slot_confirm_load_body", slot=slot_label(slot_id)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            payload = load_slot(slot_id)
            messages = payload.get("messages") or []
            rt = try_get_app_runtime()
            manager = rt.llm_manager if rt is not None else getattr(self, "deepseek", None)
            if manager is not None:
                manager.set_messages(copy.deepcopy(messages))

            rebuild_chat_history(copy.deepcopy(messages))
            self._last_user_message = last_user_text(messages)

            bg_path = str(payload.get("background_path") or "")
            if bg_path:
                self.setBackgroundImage(bg_path)
            bgm_path = str(payload.get("bgm_path") or "")
            if bgm_path and rt is not None and rt.audio_path_queue is not None:
                rt.audio_path_queue.put(
                    TTSOutputMessage(
                        audio_path=bgm_path,
                        character_name="bgm",
                        sprite="-1",
                        is_system_message=True,
                    )
                )

            if chat_history:
                replay_history_entry(self, chat_history[-1])
            else:
                self.setDisplayWords("")
            self.setNotification(
                tr(
                    "desktop.menu.save_slot_loaded",
                    slot=str(payload.get("slot_label") or slot_label(slot_id)),
                )
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.save_slot_load_failed_title"),
                tr("desktop.menu.save_slot_load_failed_body", error=str(e)),
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

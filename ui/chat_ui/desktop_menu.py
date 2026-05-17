"""主窗口设置菜单（历史、字体、语言、音量、主题等）。"""

from __future__ import annotations

import copy

import pygame
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QVBoxLayout,
)

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


class LLMApiProfileDialog(QDialog):
    def __init__(
        self,
        *,
        profile_name: str,
        profile_config: dict,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("desktop.menu.llm_profile_edit_title"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = QLineEdit(profile_name)
        self.provider_combo = QComboBox()
        try:
            from llm.llm_manager import LLMAdapterFactory

            providers = list(LLMAdapterFactory._adapters.keys())
        except Exception:
            providers = ["Deepseek", "ChatGPT", "Claude", "Gemini"]
        for provider in providers:
            self.provider_combo.addItem(provider, provider)
        provider = str(profile_config.get("provider") or "")
        ix = self.provider_combo.findData(provider)
        if ix < 0 and provider:
            self.provider_combo.addItem(provider, provider)
            ix = self.provider_combo.findData(provider)
        self.provider_combo.setCurrentIndex(ix if ix >= 0 else 0)

        self.model_edit = QLineEdit(str(profile_config.get("model") or ""))
        self.base_url_edit = QLineEdit(str(profile_config.get("base_url") or ""))
        self.api_key_edit = QLineEdit(str(profile_config.get("api_key") or ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.streaming_check = QCheckBox()
        self.streaming_check.setChecked(bool(profile_config.get("is_streaming", True)))

        form.addRow(tr("desktop.menu.profile_name"), self.name_edit)
        form.addRow(tr("desktop.menu.llm_provider"), self.provider_combo)
        form.addRow(tr("desktop.menu.profile_model"), self.model_edit)
        form.addRow(tr("desktop.menu.profile_base_url"), self.base_url_edit)
        form.addRow(tr("desktop.menu.profile_api_key"), self.api_key_edit)
        form.addRow(tr("desktop.menu.profile_streaming"), self.streaming_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def profile_name(self) -> str:
        return self.name_edit.text().strip()

    def profile_config(self, existing: dict) -> dict:
        out = dict(existing or {})
        out.update(
            {
                "provider": str(self.provider_combo.currentData() or ""),
                "base_url": self.base_url_edit.text().strip(),
                "model": self.model_edit.text().strip(),
                "api_key": self.api_key_edit.text(),
                "is_streaming": self.streaming_check.isChecked(),
            }
        )
        return out


class T2IApiProfileDialog(QDialog):
    def __init__(
        self,
        *,
        profile_name: str,
        profile_config: dict,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("desktop.menu.drawing_profile_edit_title"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = QLineEdit(profile_name)
        self.api_url_edit = QLineEdit(str(profile_config.get("api_url") or ""))
        self.model_edit = QLineEdit(str(profile_config.get("model") or ""))
        self.api_key_edit = QLineEdit(str(profile_config.get("api_key") or ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.size_combo = QComboBox()
        for size in ("auto", "1024x1024", "1024x1536", "1536x1024"):
            self.size_combo.addItem(size, size)
        size = str(profile_config.get("size") or "auto")
        ix = self.size_combo.findData(size)
        if ix < 0:
            self.size_combo.addItem(size, size)
            ix = self.size_combo.findData(size)
        self.size_combo.setCurrentIndex(ix if ix >= 0 else 0)
        self.quality_combo = QComboBox()
        for quality in ("low", "medium", "high", "auto", ""):
            self.quality_combo.addItem(quality or tr("common.auto"), quality)
        qix = self.quality_combo.findData(str(profile_config.get("quality") or "low"))
        self.quality_combo.setCurrentIndex(qix if qix >= 0 else 0)
        self.response_combo = QComboBox()
        for response_format in ("b64_json", "url", ""):
            self.response_combo.addItem(
                response_format or tr("common.auto"), response_format
            )
        rix = self.response_combo.findData(
            str(profile_config.get("response_format") or "b64_json")
        )
        self.response_combo.setCurrentIndex(rix if rix >= 0 else 0)
        self.moderation_combo = QComboBox()
        for moderation in ("", "low", "auto"):
            self.moderation_combo.addItem(moderation or tr("common.auto"), moderation)
        mix = self.moderation_combo.findData(
            str(profile_config.get("moderation") or "")
        )
        self.moderation_combo.setCurrentIndex(mix if mix >= 0 else 0)

        form.addRow(tr("desktop.menu.profile_name"), self.name_edit)
        form.addRow(tr("desktop.menu.profile_api_url"), self.api_url_edit)
        form.addRow(tr("desktop.menu.profile_model"), self.model_edit)
        form.addRow(tr("desktop.menu.profile_api_key"), self.api_key_edit)
        form.addRow(tr("desktop.menu.profile_size"), self.size_combo)
        form.addRow(tr("desktop.menu.profile_quality"), self.quality_combo)
        form.addRow(tr("desktop.menu.profile_response_format"), self.response_combo)
        form.addRow(tr("desktop.menu.profile_moderation"), self.moderation_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def profile_name(self) -> str:
        return self.name_edit.text().strip()

    def profile_config(self, existing: dict) -> dict:
        out = dict(existing or {})
        out.update(
            {
                "api_url": self.api_url_edit.text().strip(),
                "api_key": self.api_key_edit.text(),
                "model": self.model_edit.text().strip(),
                "size": str(self.size_combo.currentData() or "auto"),
                "quality": str(self.quality_combo.currentData() or ""),
                "response_format": str(self.response_combo.currentData() or ""),
                "moderation": str(self.moderation_combo.currentData() or ""),
            }
        )
        out.setdefault("auto_size", True)
        out.setdefault("square_size", "1024x1024")
        out.setdefault("portrait_size", "1024x1536")
        out.setdefault("landscape_size", "1536x1024")
        out.setdefault("timeout_seconds", 240)
        return out


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
        llm_menu = menu.addMenu(tr("desktop.menu.llm_engine"))
        try:
            from llm.provider_switcher import (
                get_active_llm_api_profile,
                list_llm_api_profiles,
            )

            llm_profiles = list_llm_api_profiles()
            active_llm_profile = get_active_llm_api_profile()
            if llm_profiles:
                for profile_name in llm_profiles:
                    action = QAction(profile_name, self)
                    action.setCheckable(True)
                    action.setChecked(profile_name == active_llm_profile)
                    action.triggered.connect(
                        lambda _checked=False, name=profile_name: (
                            self._switch_llm_api_profile(name)
                        )
                    )
                    llm_menu.addAction(action)
            else:
                empty_action = QAction(tr("desktop.menu.llm_api_profiles_empty"), self)
                empty_action.setEnabled(False)
                llm_menu.addAction(empty_action)
        except Exception:
            empty_action = QAction(tr("desktop.menu.llm_api_profiles_empty"), self)
            empty_action.setEnabled(False)
            llm_menu.addAction(empty_action)
        llm_menu.addSeparator()
        llm_save_action = QAction(tr("desktop.menu.llm_profile_save_current"), self)
        llm_edit_action = QAction(tr("desktop.menu.llm_profile_edit_current"), self)
        llm_save_action.triggered.connect(self._save_current_llm_api_profile)
        llm_edit_action.triggered.connect(self._edit_active_llm_api_profile)
        llm_menu.addAction(llm_save_action)
        llm_menu.addAction(llm_edit_action)
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
        profile_menu = drawing_menu.addMenu(tr("desktop.menu.drawing_api_profiles"))
        try:
            from t2i.provider_switcher import (
                get_active_t2i_api_profile,
                list_t2i_api_profiles,
            )

            api_profiles = list_t2i_api_profiles()
            if api_profiles:
                active_profile = get_active_t2i_api_profile()
                for profile_name in api_profiles:
                    action = QAction(profile_name, self)
                    action.setCheckable(True)
                    action.setChecked(
                        current_t2i in ("openai-image", "newapi-image", "api")
                        and profile_name == active_profile
                    )
                    action.triggered.connect(
                        lambda _checked=False, name=profile_name: (
                            self._switch_drawing_api_profile(name)
                        )
                    )
                    profile_menu.addAction(action)
            else:
                empty_action = QAction(
                    tr("desktop.menu.drawing_api_profiles_empty"), self
                )
                empty_action.setEnabled(False)
                profile_menu.addAction(empty_action)
        except Exception:
            empty_action = QAction(tr("desktop.menu.drawing_api_profiles_empty"), self)
            empty_action.setEnabled(False)
            profile_menu.addAction(empty_action)
        profile_menu.addSeparator()
        save_profile_action = QAction(
            tr("desktop.menu.drawing_profile_save_current"), self
        )
        edit_profile_action = QAction(
            tr("desktop.menu.drawing_profile_edit_current"), self
        )
        save_profile_action.triggered.connect(self._save_current_drawing_api_profile)
        edit_profile_action.triggered.connect(self._edit_active_drawing_api_profile)
        profile_menu.addAction(save_profile_action)
        profile_menu.addAction(edit_profile_action)
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

    def _active_llm_profile_config(self) -> tuple[str, dict]:
        """Return the active LLM API profile, falling back to current config."""
        config_manager.reload()
        api = config_manager.config.api_config
        active = str(getattr(api, "llm_active_api_profile", "") or "").strip()
        profiles = getattr(api, "llm_api_profiles", None) or {}
        profile = dict(profiles.get(active, {}) or {})

        provider = str(profile.get("provider") or api.llm_provider or "").strip()
        models = api.llm_model or {}
        keys = api.llm_api_key or {}
        extras = api.llm_extra_configs or {}
        profile.setdefault("provider", provider)
        profile.setdefault("base_url", str(api.llm_base_url or ""))
        profile.setdefault("model", str(models.get(provider, "") or ""))
        profile.setdefault("api_key", str(keys.get(provider, "") or ""))
        profile.setdefault("is_streaming", bool(api.is_streaming))
        profile.setdefault("temperature", float(api.temperature))
        profile.setdefault("repetition_penalty", float(api.repetition_penalty))
        profile.setdefault("presence_penalty", float(api.presence_penalty))
        profile.setdefault("frequency_penalty", float(api.frequency_penalty))
        profile.setdefault("max_context_tokens", int(api.max_context_tokens))
        profile.setdefault("extra_config", dict(extras.get(provider, {}) or {}))
        return active, profile

    def _save_current_llm_api_profile(self) -> None:
        """Save the current in-session dialog API settings as a profile."""
        self._open_llm_api_profile_dialog()

    def _edit_active_llm_api_profile(self) -> None:
        """Edit the active dialog API profile from the in-session menu."""
        self._open_llm_api_profile_dialog()

    def _open_llm_api_profile_dialog(self) -> None:
        active, profile = self._active_llm_profile_config()
        dialog = LLMApiProfileDialog(
            profile_name=active,
            profile_config=profile,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.profile_name()
        if not name:
            QMessageBox.warning(
                self,
                tr("desktop.menu.profile_save_failed_title"),
                tr("desktop.menu.profile_name_required"),
            )
            return
        try:
            from llm.provider_switcher import save_llm_api_profile

            saved = save_llm_api_profile(name, dialog.profile_config(profile))
            self._switch_llm_api_profile(saved)
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.profile_save_failed_title"),
                tr("desktop.menu.profile_save_failed_body", error=str(e)),
            )

    def _switch_llm_api_profile(self, profile_name: str) -> None:
        """切换对话 API 预设，并尽量让当前会话立刻生效。"""
        try:
            from core.runtime.app_runtime import try_get_app_runtime
            from llm.llm_manager import LLMAdapterFactory
            from llm.provider_switcher import switch_llm_api_profile

            active = switch_llm_api_profile(profile_name)
            config_manager._load_all_configs()
            api = config_manager.config.api_config
            llm_provider, llm_model, base_url, api_key = (
                config_manager.get_llm_api_config()
            )
            adapter = LLMAdapterFactory.create_adapter(
                **config_manager.merged_llm_factory_kwargs(
                    llm_provider,
                    {
                        "llm_provider": llm_provider,
                        "api_key": api_key,
                        "base_url": base_url,
                        "model": llm_model,
                    },
                )
            )
            rt = try_get_app_runtime()
            if rt is not None and rt.llm_manager is not None:
                messages = list(rt.llm_manager.get_messages())
                user_template = rt.llm_manager.user_template
                if hasattr(adapter, "set_user_template"):
                    adapter.set_user_template(user_template)
                rt.llm_manager.set_adapter(adapter)
                rt.llm_manager.set_messages(messages)
                rt.llm_manager.generation_config = {
                    "temperature": float(api.temperature),
                    "repetition_penalty": float(api.repetition_penalty),
                    "presence_penalty": float(api.presence_penalty),
                    "frequency_penalty": float(api.frequency_penalty),
                    "max_tokens": 4096,
                }
                rt.llm_manager.compact_manager.max_tokens = int(
                    api.max_context_tokens
                )
            self.setNotification(
                tr("desktop.menu.notify_llm_api_profile", profile=active)
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.llm_switch_failed_title"),
                tr("desktop.menu.llm_switch_failed_body", error=str(e)),
            )

    def _active_t2i_profile_config(self) -> tuple[str, dict]:
        """Return the active remote drawing API profile, falling back to config."""
        try:
            from t2i.provider_switcher import (
                get_active_t2i_api_profile,
                list_t2i_api_profiles,
            )

            list_t2i_api_profiles()
            active = get_active_t2i_api_profile()
        except Exception:
            active = ""

        config_manager.reload()
        api = config_manager.config.api_config
        active = str(active or getattr(api, "t2i_active_api_profile", "") or "")
        profiles = getattr(api, "t2i_api_profiles", None) or {}
        profile = dict(profiles.get(active, {}) or {})
        api_extra = dict((api.t2i_extra_configs or {}).get("openai-image", {}) or {})
        for key, value in api_extra.items():
            profile.setdefault(key, value)
        profile.setdefault("api_url", str(api.t2i_api_url or ""))
        profile.setdefault("api_key", "")
        profile.setdefault("model", "gpt-image-2")
        profile.setdefault("size", "auto")
        profile.setdefault("quality", "low")
        profile.setdefault("response_format", "b64_json")
        profile.setdefault("moderation", "low")
        profile.setdefault("auto_size", True)
        profile.setdefault("square_size", "1024x1024")
        profile.setdefault("portrait_size", "1024x1536")
        profile.setdefault("landscape_size", "1536x1024")
        profile.setdefault("timeout_seconds", 240)
        return active, profile

    def _save_current_drawing_api_profile(self) -> None:
        """Save the current in-session drawing API settings as a profile."""
        self._open_drawing_api_profile_dialog()

    def _edit_active_drawing_api_profile(self) -> None:
        """Edit the active drawing API profile from the in-session menu."""
        self._open_drawing_api_profile_dialog()

    def _open_drawing_api_profile_dialog(self) -> None:
        active, profile = self._active_t2i_profile_config()
        dialog = T2IApiProfileDialog(
            profile_name=active,
            profile_config=profile,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.profile_name()
        if not name:
            QMessageBox.warning(
                self,
                tr("desktop.menu.profile_save_failed_title"),
                tr("desktop.menu.profile_name_required"),
            )
            return
        try:
            from t2i.provider_switcher import save_t2i_api_profile

            saved = save_t2i_api_profile(name, dialog.profile_config(profile))
            self._switch_drawing_api_profile(saved)
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("desktop.menu.profile_save_failed_title"),
                tr("desktop.menu.profile_save_failed_body", error=str(e)),
            )

    def _switch_drawing_api_profile(self, profile_name: str) -> None:
        """切换远程绘画 API 预设，并尽量让当前会话立刻生效。"""
        try:
            from core.runtime.app_runtime import try_get_app_runtime
            from t2i.provider_switcher import switch_t2i_api_profile
            from t2i.t2i_manager import T2IAdapterFactory, T2IManager

            active = switch_t2i_api_profile(profile_name)
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
            self.setNotification(
                tr("desktop.menu.notify_drawing_api_profile", profile=active)
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

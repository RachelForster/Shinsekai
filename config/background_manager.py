"""Thin compatibility facade delegating background mutations to ``config.background_ops``."""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from config.background_ops import (
    BackgroundProfileError,
    ConfigManagerBackgroundTarget,
    delete_all_background_bgms,
    delete_all_background_sprites,
    delete_background_and_assets,
    delete_single_background_bgm,
    delete_single_background_sprite,
    save_background_bgm_tags_op,
    save_background_image_tags_op,
    save_background_patch,
    upload_background_bgms,
    upload_background_sprites,
)
from config.config_manager import ConfigManager
from config.schema import Background, Sprite
from i18n import LocalizedErrorStr, err_tr, is_operation_error_message, tr
import tools.file_util as fu

if TYPE_CHECKING:
    import pandas as pd

BACKGROUND_CONFIG_PATH = ConfigManager._BACKGOUND_CONFIG_PATH
BACKGROUND_UPLOAD_DIR = "data/backgrounds"
BGM_UPLOAD_DIR = "data/bgm"


def _pd():
    import pandas as pd

    return pd


class BackgroundManager:
    """Compatibility facade over ``ConfigManager`` and ``config.background_ops``."""

    _llm_manager: Optional[Any] = None
    _config_manager: ConfigManager

    def __init__(self) -> None:
        self._config_manager = ConfigManager()

    def _target(self) -> ConfigManagerBackgroundTarget:
        return ConfigManagerBackgroundTarget(self._config_manager, save_fn=self._save_background_config, custom_save="_save_background_config" in getattr(self, "__dict__", {}))

    def _get_background_list(self) -> List[Background]:
        try:
            return self._config_manager.config.background_list
        except Exception:
            return []

    def get_background_name_list(self) -> List[str]:
        return [b.name for b in self._config_manager.config.background_list]

    def _save_background_config(self) -> None:
        self._config_manager.save_background_config()

    def save_background_patch(
        self,
        patch: Mapping[str, Any],
        *,
        original_name: Optional[str] = None,
        target_id: Optional[str] = None,
    ) -> tuple[Background, str | None, bool]:
        """Validate and apply a partial or full background patch."""
        return save_background_patch(self._target(), patch, original_name=original_name, target_id=target_id)

    def add_background(
        self,
        name: str,
        sprite_prefix: str = "temp",
        edit_as_name: Optional[str] = None,
        bg_tags: Optional[str] = None,
        bgm_tags: Optional[str] = None,
        **extra_fields: Any,
    ) -> Tuple[str, List[str]]:
        patch: dict[str, Any] = {**extra_fields, "name": name, "sprite_prefix": sprite_prefix}
        if bg_tags is not None:
            patch["bg_tags"] = bg_tags
        if bgm_tags is not None:
            patch["bgm_tags"] = bgm_tags
        try:
            _saved, _renamed, created = self.save_background_patch(patch, original_name=edit_as_name)
        except BackgroundProfileError as exc:
            return LocalizedErrorStr(exc), [b.name for b in self._get_background_list()]
        return (tr("crud.bg.added") if created else tr("crud.bg.updated"), [b.name for b in self._get_background_list()])

    def delete_background(self, name: str) -> Tuple[str, List[str]]:
        return delete_background_and_assets(self._target(), name, upload_dir=BACKGROUND_UPLOAD_DIR, bgm_dir=BGM_UPLOAD_DIR)

    def upload_sprites(self, background_name: str, sprite_files: List[Any], bg_tags: str) -> Tuple[str, List[str], str]:
        return upload_background_sprites(self._target(), background_name, sprite_files, bg_tags, upload_dir=BACKGROUND_UPLOAD_DIR)

    def delete_all_sprites(self, background_name: str) -> Tuple[str, List[str], str]:
        return delete_all_background_sprites(self._target(), background_name, upload_dir=BACKGROUND_UPLOAD_DIR)

    def delete_single_sprite(self, background_name: str, sprite_index: int) -> Tuple[str, List[str], str]:
        return delete_single_background_sprite(self._target(), background_name, sprite_index)

    def upload_bg_tags(self, background_name: str, bg_tags: str) -> str:
        try:
            save_background_image_tags_op(self._target(), background_name, bg_tags)
            return tr("crud.common.tag_success")
        except BackgroundProfileError as exc:
            return LocalizedErrorStr(exc)
        except Exception as exc:
            return err_tr("crud.common.tag_failed", error=exc)

    def get_background_sprites(self, background_name: str) -> Tuple[List[str], str, List[Any]]:
        background = self._config_manager.get_background_by_name(background_name) if background_name else None
        if not background:
            return [], "", []
        paths = [s.path if isinstance(s, Sprite) else s.get("path", "") for s in (background.sprites or []) if s]
        return paths, background.bg_tags or "", []

    def load_backgrounds_from_file(self) -> Tuple[str, List[List[str]]]:
        try:
            self._config_manager.reload()
            return tr("crud.bg.loaded"), [[b.name, b.sprite_prefix, b.bg_tags or ""] for b in self._get_background_list()]
        except Exception as exc:
            return err_tr("crud.common.load_failed", error=exc), [[b.name, b.sprite_prefix, b.bg_tags or ""] for b in self._get_background_list()]

    def upload_bgms(self, background_name: str, bgm_files: List[Any]) -> Any:
        message, _paths, tags = upload_background_bgms(self._target(), background_name, bgm_files, bgm_dir=BGM_UPLOAD_DIR)
        if is_operation_error_message(message):
            return message, _pd().DataFrame(), tags
        df, loaded_tags = self.load_bgms_and_tags(background_name)
        return message, df, loaded_tags

    def delete_all_bgms(self, background_name: str) -> Tuple[str, List[str], str]:
        return delete_all_background_bgms(self._target(), background_name, bgm_dir=BGM_UPLOAD_DIR)

    def upload_bgm_tags(self, background_name: str, bgm_tags: str) -> str:
        try:
            save_background_bgm_tags_op(self._target(), background_name, bgm_tags)
            return tr("crud.bg.bgm_tag_success")
        except BackgroundProfileError as exc:
            return LocalizedErrorStr(exc)
        except Exception as exc:
            return err_tr("crud.bg.bgm_tag_failed", error=exc)

    def get_background_bgms(self, background_name: str) -> Tuple[List[str], str, List[Any]]:
        background = self._config_manager.get_background_by_name(background_name) if background_name else None
        if not background:
            return [], "", []
        return getattr(background, "bgm_list", []), getattr(background, "bgm_tags", ""), []

    def format_bgms_for_display(self, bgm_paths: List[str], bgm_tags: str) -> pd.DataFrame:
        tags_list = bgm_tags.strip().split("\n") if bgm_tags else []
        rows = [
            {
                "选择": False, "序号": i + 1, "文件名": os.path.basename(path), "路径": path,
                "标签描述": (tags_list[i].split("：", 1)[-1].strip() if "：" in tags_list[i] else tags_list[i]) if i < len(tags_list) else "",
            }
            for i, path in enumerate(bgm_paths)
        ]
        return _pd().DataFrame(rows)

    def load_bgms_and_tags(self, background_name: str) -> Tuple[pd.DataFrame, str]:
        if not background_name:
            return _pd().DataFrame(), ""
        bgm_paths, bgm_tags, _ = self.get_background_bgms(background_name)
        return self.format_bgms_for_display(bgm_paths, bgm_tags), bgm_tags

    def delete_single_bgm(self, background_name: str, bgm_index: int) -> Tuple[str, List[str], str]:
        return delete_single_background_bgm(self._target(), background_name, bgm_index)

    def batch_delete_bgms(self, background_name: str, bgm_dataframe: pd.DataFrame, bgm_tags: str) -> Any:
        if not background_name:
            return err_tr("crud.bg.select_first"), _pd().DataFrame(), bgm_tags
        if bgm_dataframe.empty:
            return err_tr("crud.bg.no_bgm_to_delete"), _pd().DataFrame(), ""
        try:
            indices = sorted(bgm_dataframe[bgm_dataframe["选择"] == True]["序号"].tolist(), reverse=True)  # noqa: E712
        except Exception as exc:
            return err_tr("crud.bg.bgm_dataframe_failed", error=exc), bgm_dataframe, bgm_tags
        if not indices:
            return err_tr("crud.bg.select_bgm_rows"), bgm_dataframe, bgm_tags
        deleted, errors = 0, ""
        for original_index in indices:
            try:
                msg, _, _ = self.delete_single_bgm(background_name, original_index - 1)
                deleted += 0 if is_operation_error_message(msg) else 1
                if is_operation_error_message(msg):
                    errors += tr("crud.bg.bgm_row_delete_failed", index=original_index, message=msg)
            except Exception as exc:
                errors += tr("crud.bg.bgm_row_delete_error", index=original_index, error=exc)
        paths, remaining_tags, _ = self.get_background_bgms(background_name)
        summary = tr("crud.bg.bgm_bulk_deleted", count=deleted) + (tr("crud.bg.bgm_partial_errors", errors=errors) if errors else "")
        return summary, self.format_bgms_for_display(paths, remaining_tags), remaining_tags

    def handle_bgm_selection(self, evt: Any, bgm_dataframe: pd.DataFrame) -> Tuple[str, str]:
        if evt is None or evt.index is None:
            return err_tr("crud.bg.click_row"), ""
        row_index = evt.index[0]
        if not 0 <= row_index < len(bgm_dataframe):
            return err_tr("crud.bg.invalid_row"), ""
        try:
            selected_path = bgm_dataframe.iloc[row_index]["路径"]
            if not selected_path or not os.path.exists(selected_path):
                return err_tr("crud.bg.file_missing", path=selected_path), ""
            return tr("crud.bg.playing", filename=os.path.basename(selected_path)), selected_path
        except KeyError:
            return err_tr("crud.bg.missing_path_column"), ""
        except Exception as exc:
            return err_tr("crud.bg.play_failed", error=exc), ""

    def export_background_file(self, background_name: str) -> str:
        try:
            background = self._config_manager.get_background_by_name(background_name)
            if not background:
                return err_tr("crud.bg.not_found", name=background_name)
            fu.export_background([background], f"./output/{background_name}.bg")
            return tr("crud.bg.exported", name=background_name)
        except Exception as exc:
            return err_tr("crud.bg.export_failed", error=exc)

    def import_background_file(self, input_path: str) -> Tuple[str, List[str]]:
        try:
            existing = self._config_manager.config.background_list
            imported = fu.import_background(input_path, existing)
            for item in imported:
                if item not in existing:
                    existing.append(item)
            self._config_manager.save_background_config()
            return tr("crud.bg.imported", count=len(imported)), [b.name for b in existing]
        except Exception as exc:
            return err_tr("crud.bg.import_failed", error=exc), [b.name for b in self._get_background_list()]

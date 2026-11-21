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
        return ConfigManagerBackgroundTarget(self._config_manager, save_fn=self._save_background_config)

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
            return str(exc), [b.name for b in self._get_background_list()]
        return ("背景组已添加！" if created else "背景组已更新！", [b.name for b in self._get_background_list()])

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
            return "标注成功！"
        except BackgroundProfileError as exc:
            return str(exc)
        except Exception as exc:
            return f"标注出错了：{exc}"

    def get_background_sprites(self, background_name: str) -> Tuple[List[str], str, List[Any]]:
        background = self._config_manager.get_background_by_name(background_name) if background_name else None
        if not background:
            return [], "", []
        paths = [s.path if isinstance(s, Sprite) else s.get("path", "") for s in (background.sprites or []) if s]
        return paths, background.bg_tags or "", []

    def load_backgrounds_from_file(self) -> Tuple[str, List[List[str]]]:
        try:
            self._config_manager.reload()
            return "背景设定已加载！", [[b.name, b.sprite_prefix, b.bg_tags or ""] for b in self._get_background_list()]
        except Exception as exc:
            return f"加载失败: {exc}", [[b.name, b.sprite_prefix, b.bg_tags or ""] for b in self._get_background_list()]

    def upload_bgms(self, background_name: str, bgm_files: List[Any]) -> Any:
        message, _paths, tags = upload_background_bgms(self._target(), background_name, bgm_files, bgm_dir=BGM_UPLOAD_DIR)
        if message.startswith(("请先", "请选择", "找不到")):
            return message, _pd().DataFrame(), tags
        df, loaded_tags = self.load_bgms_and_tags(background_name)
        return message, df, loaded_tags

    def delete_all_bgms(self, background_name: str) -> Tuple[str, List[str], str]:
        return delete_all_background_bgms(self._target(), background_name, bgm_dir=BGM_UPLOAD_DIR)

    def upload_bgm_tags(self, background_name: str, bgm_tags: str) -> str:
        try:
            save_background_bgm_tags_op(self._target(), background_name, bgm_tags)
            return "背景音乐标注成功！"
        except BackgroundProfileError as exc:
            return str(exc)
        except Exception as exc:
            return f"背景音乐标注出错了：{exc}"

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
            return "请先选择背景组！", _pd().DataFrame(), bgm_tags
        if bgm_dataframe.empty:
            return "没有音乐条可供删除。", _pd().DataFrame(), ""
        try:
            indices = sorted(bgm_dataframe[bgm_dataframe["选择"] == True]["序号"].tolist(), reverse=True)  # noqa: E712
        except Exception as exc:
            return f"处理数据失败: {exc}", bgm_dataframe, bgm_tags
        if not indices:
            return "请勾选要删除的音乐条。", bgm_dataframe, bgm_tags
        deleted, errors = 0, ""
        for original_index in indices:
            try:
                msg, _, _ = self.delete_single_bgm(background_name, original_index - 1)
                deleted += 1 if "已删除" in msg else 0
                if "已删除" not in msg:
                    errors += f"删除序号 {original_index} 失败: {msg}\n"
            except Exception as exc:
                errors += f"删除序号 {original_index} 发生异常: {exc}\n"
        paths, remaining_tags, _ = self.get_background_bgms(background_name)
        summary = f"成功删除了 {deleted} 个音乐条。" + (f"\n部分删除失败的提示：\n{errors}" if errors else "")
        return summary, self.format_bgms_for_display(paths, remaining_tags), remaining_tags

    def handle_bgm_selection(self, evt: Any, bgm_dataframe: pd.DataFrame) -> Tuple[str, str]:
        if evt is None or evt.index is None:
            return "请点击 Dataframe 中的一行。", ""
        row_index = evt.index[0]
        if not 0 <= row_index < len(bgm_dataframe):
            return "无效的行选择。", ""
        try:
            selected_path = bgm_dataframe.iloc[row_index]["路径"]
            if not selected_path or not os.path.exists(selected_path):
                return f"文件路径不存在: {selected_path}", ""
            return f"正在播放: {os.path.basename(selected_path)}", selected_path
        except KeyError:
            return "Dataframe 缺少 '路径' 列，无法播放。", ""
        except Exception as exc:
            return f"播放出错: {exc}", ""

    def export_background_file(self, background_name: str) -> str:
        try:
            background = self._config_manager.get_background_by_name(background_name)
            if not background:
                return f"找不到背景组: {background_name}"
            fu.export_background([background], f"./output/{background_name}.bg")
            return f"背景组已导出到: /output/{background_name}.bg"
        except Exception as exc:
            return f"背景导出失败: {exc}"

    def import_background_file(self, input_path: str) -> Tuple[str, List[str]]:
        try:
            existing = self._config_manager.config.background_list
            imported = fu.import_background(input_path, existing)
            for item in imported:
                if item not in existing:
                    existing.append(item)
            self._config_manager.save_background_config()
            return f"成功导入 {len(imported)} 个背景组！", [b.name for b in existing]
        except Exception as exc:
            return f"背景导入失败: {exc}", [b.name for b in self._get_background_list()]

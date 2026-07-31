from __future__ import annotations

import os
from copy import deepcopy
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, List, Dict, Any, Tuple, Optional, Union
from config.schema import Background, Sprite # 确保导入了 Background 和 Sprite
from config.config_manager import ConfigManager
import tools.file_util as fu
import yaml
from sdk.file_transactions import (
    copy_file_exclusive_with_identity,
    portable_name_key,
    remove_directory_without_links,
    remove_empty_directory_without_links,
    remove_file_without_links,
)
from sdk.path_contract import (
    managed_project_directory,
    managed_project_file,
    portable_project_path,
    project_root,
    resolve_runtime_asset_path,
    resolve_runtime_asset_read_path,
    safe_path_component,
)

if TYPE_CHECKING:
    import pandas as pd

# 不在此模块顶层 import UI 框架；配置模型必须可由 bridge 与 CLI 轻量加载。
# PyInstaller 需为各子包补数据文件。旧 Gradio WebUI 仍通过本类；仅 handle_bgm_selection 在 Gradio 下使用。

BACKGROUND_UPLOAD_DIR = "data/backgrounds"
BGM_UPLOAD_DIR = "data/bgm"

_BACKGROUND_IO_LOCK = RLock()


def _serialized_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _BACKGROUND_IO_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _restore_model(target: Any, snapshot: Any) -> None:
    for field_name in type(target).model_fields:
        setattr(target, field_name, deepcopy(getattr(snapshot, field_name)))


def _unlink_created_files(
    paths: List[tuple[Path, os.stat_result]],
) -> None:
    for path, identity in reversed(paths):
        try:
            remove_file_without_links(
                path,
                missing_ok=True,
                expected_identity=identity,
            )
        except (OSError, ValueError):
            pass


def _pd():
    import pandas as pd

    return pd


def _managed_directory_snapshot(
    root: Path,
    base_dir: str,
    component: str,
) -> tuple[Path, os.stat_result] | None:
    try:
        target = managed_project_directory(base_dir, component, root=root)
    except (OSError, PermissionError, ValueError):
        return None
    try:
        identity = target.lstat()
    except FileNotFoundError:
        return None
    return (target, identity) if target.is_dir() else None


def _remove_managed_directory(
    root: Path,
    base_dir: str,
    component: str,
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    snapshot = _managed_directory_snapshot(root, base_dir, component)
    if snapshot is None:
        return
    target, current_identity = snapshot
    if (
        expected_identity is not None
        and not os.path.samestat(expected_identity, current_identity)
    ):
        return
    try:
        remove_directory_without_links(
            target,
            expected_identity=current_identity,
        )
    except OSError:
        pass


def _managed_file_snapshot(
    root: Path,
    base_dir: str,
    raw_path: str,
) -> tuple[Path, os.stat_result] | None:
    try:
        target = managed_project_file(raw_path, base_dir, root=root)
    except (OSError, PermissionError, ValueError):
        return None
    if target is None:
        return None
    try:
        identity = target.lstat()
    except FileNotFoundError:
        return None
    return (target, identity) if target.is_file() else None


def _unlink_managed_file(
    root: Path,
    base_dir: str,
    raw_path: str,
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    snapshot = _managed_file_snapshot(root, base_dir, raw_path)
    if snapshot is None:
        return
    target, current_identity = snapshot
    if (
        expected_identity is not None
        and not os.path.samestat(expected_identity, current_identity)
    ):
        return
    try:
        remove_file_without_links(
            target,
            expected_identity=current_identity,
        )
    except (OSError, ValueError):
        pass


def _prefix_in_use(backgrounds: List[Background], prefix: str) -> bool:
    key = _prefix_key(prefix)
    return bool(key) and any(
        _prefix_key(background.sprite_prefix) == key
        for background in backgrounds
    )


def _prefix_key(value: Any) -> str:
    raw = str(value or "")
    try:
        return portable_name_key(safe_path_component(raw, field="sprite_prefix"))
    except ValueError:
        return ""


def _managed_background_path_in_use(
    manager: "BackgroundManager",
    raw_path: str,
    *,
    kind: str,
    base_dir: str,
) -> bool:
    try:
        target = managed_project_file(raw_path, base_dir, root=manager._project_root)
    except (OSError, PermissionError, ValueError):
        return False
    if target is None:
        return False
    for background in manager._config_manager.config.background_list:
        if kind == "sprite":
            values = [
                sprite.path if isinstance(sprite, Sprite) else sprite.get("path", "")
                for sprite in (background.sprites or [])
            ]
        else:
            values = list(background.bgm_list or [])
        for candidate_raw in values:
            try:
                candidate = managed_project_file(
                    str(candidate_raw or ""),
                    base_dir,
                    root=manager._project_root,
                )
            except (OSError, PermissionError, ValueError):
                continue
            if candidate == target:
                return True
    return False


class BackgroundManager:
    """
    负责背景配置和背景图片（Sprite）的管理。
    内部使用 ConfigManager 来持久化数据。
    """
    
    # 私有属性，用于缓存 LLM Manager 实例 (在此处不相关, 但保留结构)
    _llm_manager: Optional[Any] = None 
    _config_manager: ConfigManager
    
    def __init__(self):
        """初始化 BackgroundManager，获取 ConfigManager 单例。"""
        self._config_manager = ConfigManager()
        self._project_root = project_root()

    def _get_background_list(self) -> List[Background]:
        """获取当前的 Background 列表"""
        try:
            return self._config_manager.config.background_list
        except Exception:
            # 如果配置未加载或失败，返回空列表
            return []
            
    def get_background_name_list(self):
        """获取所有背景组的名称列表"""
        return [b.name for b in self._config_manager.config.background_list]

    def _save_background_config(self) -> None:
        """保存背景配置的便捷方法"""
        self._config_manager.save_background_config()

    @_serialized_mutation
    def add_background(
        self,
        name: str,
        sprite_prefix: str,
        edit_as_name: Optional[str] = None,
        bg_tags: Optional[str] = None,
        bgm_tags: Optional[str] = None,
    ) -> Tuple[str, List[str]]:
        """
        添加或更新背景配置。

        若 edit_as_name 为当前列表中已存在的名字（如 UI 下拉当前选中项），
        则按该条记录更新；名称栏改为新名字时视为重命名，不会新建另一组背景。

        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有背景名称列表)
        """
        current_names = [b.name for b in self._get_background_list()]
        if not name:
            return "名称不能为空！", current_names

        background_list = self._config_manager.config.background_list
        try:
            sprite_prefix = safe_path_component(
                str(sprite_prefix or ""),
                field="sprite_prefix",
            )
        except ValueError:
            return "背景目录名无效！", current_names

        prefix_key = portable_name_key(sprite_prefix)
        edit_target_name = str(edit_as_name or "").strip()
        for background in background_list:
            if _prefix_key(background.sprite_prefix) != prefix_key:
                continue
            if edit_target_name and background.name.casefold() == edit_target_name.casefold():
                continue
            return (
                f"背景目录名「{sprite_prefix}」已被背景组「{background.name}」占用！",
                current_names,
            )

        if edit_target_name:
            target = self._config_manager.get_background_by_name(edit_target_name)
            if target is not None:
                if str(target.sprite_prefix or "") != sprite_prefix:
                    return (
                        "背景资源目录创建后不可直接修改；请新建背景组后迁移资源。",
                        [b.name for b in background_list],
                    )
                taken = self._config_manager.get_background_by_name(name)
                if taken is not None and taken is not target:
                    return f"名称「{name}」已与其他背景组重复！", [b.name for b in background_list]
                snapshot = target.model_copy(deep=True)
                try:
                    target.name = name
                    target.sprite_prefix = sprite_prefix
                    if bg_tags is not None:
                        target.bg_tags = bg_tags
                    if bgm_tags is not None:
                        target.bgm_tags = bgm_tags
                    self._save_background_config()
                except BaseException:
                    _restore_model(target, snapshot)
                    raise
                return "背景组已更新！", [b.name for b in background_list]

        existing_background: Optional[Background] = self._config_manager.get_background_by_name(name)

        if existing_background is None:
            # 创建新的 Background 实例
            new_background = Background( # 修正变量名和类型
                name=name,
                sprite_prefix=sprite_prefix,
                sprites=[],
                bg_tags=bg_tags or "",
                bgm_list=[],
                bgm_tags=bgm_tags or "",
            )    
            background_list.append(new_background)
            try:
                self._save_background_config()
            except BaseException:
                if background_list and background_list[-1] is new_background:
                    background_list.pop()
                else:
                    try:
                        background_list.remove(new_background)
                    except ValueError:
                        pass
                raise
            return "背景组已添加！", [b.name for b in background_list] # 修正返回消息
        else:
            # 更新现有 Background 实例的属性
            if str(existing_background.sprite_prefix or "") != sprite_prefix:
                return (
                    "背景资源目录创建后不可直接修改；请新建背景组后迁移资源。",
                    [b.name for b in background_list],
                )
            snapshot = existing_background.model_copy(deep=True)
            try:
                existing_background.name = name
                existing_background.sprite_prefix = sprite_prefix
                if bg_tags is not None:
                    existing_background.bg_tags = bg_tags
                if bgm_tags is not None:
                    existing_background.bgm_tags = bgm_tags
                self._save_background_config()
            except BaseException:
                _restore_model(existing_background, snapshot)
                raise
            return "背景组已更新！", [b.name for b in background_list] # 修正返回消息


    @_serialized_mutation
    def delete_background(self, name: str) -> Tuple[str, List[str]]:
        """
        删除背景组及其相关文件。
        
        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有背景名称列表)
        """
        background_list = self._config_manager.config.background_list # 修正变量名
        current_names = [b.name for b in background_list]
        
        if not name or name == "新背景": # 修正提示
            return "请选择要删除的背景组！", current_names
        
        background_to_delete: Optional[Background] = self._config_manager.get_background_by_name(name) # 修正方法
        
        if background_to_delete is None:
            return f"找不到背景组: {name}", current_names

        sprite_prefix = background_to_delete.sprite_prefix
        directory_snapshots = {
            base_dir: _managed_directory_snapshot(
                self._project_root,
                base_dir,
                sprite_prefix,
            )
            for base_dir in (BACKGROUND_UPLOAD_DIR, BGM_UPLOAD_DIR)
        } if sprite_prefix else {}

        original_index = background_list.index(background_to_delete)
        try:
            background_list.remove(background_to_delete)
        except ValueError:
            return f"找不到背景组: {name}", current_names
        try:
            self._save_background_config()
        except BaseException:
            background_list.insert(original_index, background_to_delete)
            raise
        new_names = [b.name for b in background_list]

        if not sprite_prefix:
            return "已删除背景组", new_names
        
        if not _prefix_in_use(background_list, sprite_prefix):
            for base_dir in (BACKGROUND_UPLOAD_DIR, BGM_UPLOAD_DIR):
                directory_snapshot = directory_snapshots.get(base_dir)
                if directory_snapshot is not None:
                    _remove_managed_directory(
                        self._project_root,
                        base_dir,
                        sprite_prefix,
                        expected_identity=directory_snapshot[1],
                    )
        
        return f"背景组 {name} 已删除！", new_names

    @_serialized_mutation
    def upload_sprites(self, background_name: str, sprite_files: List[Any], bg_tags: str) -> Tuple[str, List[str], str]: # 修正参数名
        """
        上传背景图片文件并更新背景的图片列表和标签。

        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 所有背景图片路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择或创建背景组！", [], '' # 修正提示
        
        if not sprite_files:
            return "请选择要上传的图片！", [], ''
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}", [], '' # 修正提示
        
        # 修正目录，使用 Background 的 prefix 和 BACKGROUND_UPLOAD_DIR
        try:
            bg_dir = managed_project_directory(
                BACKGROUND_UPLOAD_DIR,
                background.sprite_prefix,
                root=self._project_root,
            )
        except (PermissionError, ValueError):
            return "背景目录名无效！", [], bg_tags
        directory_was_missing = not bg_dir.exists()
        created_directory_identity: os.stat_result | None = None
        snapshot = background.model_copy(deep=True)
        created_files: List[tuple[Path, os.stat_result]] = []
        try:
            if background.sprites is None:
                background.sprites = []

            num_existing_sprites = len(background.sprites)
            bg_tags_to_add = ''

            for i, file in enumerate(sprite_files):
                source = resolve_runtime_asset_read_path(
                    file.name,
                    root=self._project_root,
                )
                filename = safe_path_component(
                    source.name,
                    field="background filename",
                )
                dest_path, dest_identity = copy_file_exclusive_with_identity(
                    source,
                    bg_dir,
                    filename,
                    field="background filename",
                )
                created_files.append((dest_path, dest_identity))
                if (
                    directory_was_missing
                    and created_directory_identity is None
                ):
                    created_directory_identity = bg_dir.lstat()
                stored_path = portable_project_path(dest_path, root=self._project_root)
                background.sprites.append({"path": stored_path})
                bg_tags_to_add += f'场景 {num_existing_sprites + i + 1}：\n'

            current_bg_tags = background.bg_tags if background.bg_tags else ""
            background.bg_tags = current_bg_tags + bg_tags_to_add
            self._config_manager.save_background_config()
        except BaseException:
            _restore_model(background, snapshot)
            _unlink_created_files(created_files)
            if directory_was_missing and created_directory_identity is not None:
                try:
                    remove_empty_directory_without_links(
                        bg_dir,
                        expected_identity=created_directory_identity,
                    )
                except (OSError, ValueError):
                    pass
            raise

        all_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites]
        return f"成功为 {background_name} 上传 {len(sprite_files)} 张背景图片！", all_sprite_paths, background.bg_tags # 修正消息


    @_serialized_mutation
    def delete_all_sprites(self, background_name: str) -> Tuple[str, List[str], str]: # 修正参数名
        """
        删除背景组的所有背景图片。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 空图片路径列表, 空标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], "" # 修正提示
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}", [], "" # 修正提示

        directory_snapshot = _managed_directory_snapshot(
            self._project_root,
            BACKGROUND_UPLOAD_DIR,
            background.sprite_prefix,
        )
        snapshot = background.model_copy(deep=True)
        try:
            background.sprites = []
            background.bg_tags = ""
            self._config_manager.save_background_config()
        except BaseException:
            _restore_model(background, snapshot)
            raise

        others = [
            item
            for item in self._config_manager.config.background_list
            if item is not background
        ]
        if (
            directory_snapshot is not None
            and not _prefix_in_use(others, background.sprite_prefix)
        ):
            _remove_managed_directory(
                self._project_root,
                BACKGROUND_UPLOAD_DIR,
                background.sprite_prefix,
                expected_identity=directory_snapshot[1],
            )
        
        return f"已删除 {background_name} 的所有背景图片！", [], "" # 修正消息


    @_serialized_mutation
    def delete_single_sprite(self, background_name: str, sprite_index: int) -> Tuple[str, List[str], str]: # 修正参数名
        """
        删除背景组的指定背景图片。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 剩余图片路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], "" # 修正提示
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}", [], "" # 修正提示
        
        # 索引检查
        if not background.sprites or sprite_index < 0 or sprite_index >= len(background.sprites):
            remaining_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites]
            return "背景图片不存在！", remaining_paths, background.bg_tags # 修正提示和属性
        
        sprite_data: Union[Sprite, dict] = background.sprites[sprite_index]
        
        # 获取路径
        sprite_path = sprite_data.path if isinstance(sprite_data, Sprite) else sprite_data.get("path", "")
        sprite_snapshot = _managed_file_snapshot(
            self._project_root,
            BACKGROUND_UPLOAD_DIR,
            str(sprite_path),
        ) if sprite_path else None
        # 背景图片没有语音文件，移除 voice_path 相关代码
        
        snapshot = background.model_copy(deep=True)
        background.sprites.pop(sprite_index)
        
        # 更新标签
        bg_tags = ""
        original_tags_list = background.bg_tags.strip().split('\n') if background.bg_tags else [] # 修正属性
        
        if sprite_index < len(original_tags_list):
            original_tags_list.pop(sprite_index)
        
        for i, line in enumerate(original_tags_list):
            # 尝试解析并重建标签行
            parts = line.split('：') if '：' in line else line.split(':')
            current_tag = parts[-1].strip() if len(parts) > 1 else ""
            bg_tags += f'场景 {i+1}：{current_tag}\n' # 修正标签前缀
            
        background.bg_tags = bg_tags
        try:
            self._config_manager.save_background_config()
        except BaseException:
            _restore_model(background, snapshot)
            raise

        if sprite_snapshot is not None and not _managed_background_path_in_use(
            self,
            str(sprite_path),
            kind="sprite",
            base_dir=BACKGROUND_UPLOAD_DIR,
        ):
            _unlink_managed_file(
                self._project_root,
                BACKGROUND_UPLOAD_DIR,
                str(sprite_path),
                expected_identity=sprite_snapshot[1],
            )
        
        remaining_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites]
        return f"已删除 {background_name} 的第 {sprite_index+1} 张背景图片！", remaining_sprite_paths, bg_tags # 修正消息


    @_serialized_mutation
    def upload_bg_tags(self, background_name: str, bg_tags: str) -> str: # 修正函数名和参数名
        """
        上传/更新背景的标签文本。
        
        Returns:
            str: 操作结果消息。
        """
        if not background_name:
            return "请先选择或创建背景组！" # 修正提示
        
        if not bg_tags: # 修正变量名
            return "请输入背景标注！" # 修正提示
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        if not background:
            return f"找不到背景组: {background_name}" # 修正提示
        
        snapshot = background.model_copy(deep=True)
        try:
            background.bg_tags = bg_tags # 修正属性
            self._config_manager.save_background_config() # 修正保存方法
            return "标注成功！"
        except Exception as e:
            _restore_model(background, snapshot)
            return f"标注出错了：{e}"

    def get_background_sprites(self, background_name: str) -> Tuple[List[str], str, List[Any]]: # 修正函数名和参数名
        """
        获取指定背景组的所有背景图片路径和标签。
        
        Returns:
            Tuple[List[str], str, List[Any]]: (图片路径列表, 标签文本, 额外的返回列表 (始终为空))
        """
        if not background_name:
            return [], "", []
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name) # 修正方法
        
        if not background:
            return [], "", []

        sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in background.sprites if s]
        bg_tags = background.bg_tags if background.bg_tags else "" # 修正属性
        
        return sprite_paths, bg_tags, []


    def load_backgrounds_from_file(self) -> Tuple[str, List[List[str]]]: # 修正函数名
        """
        重新加载背景设定文件。
        
        Returns:
            Tuple[str, List[List[str]]]: (操作结果消息, 背景信息列表: [[name, sprite_prefix, bg_tags], ...])
        """
        try:
            self._config_manager.reload()
            background_list = self._config_manager.config.background_list # 修正列表名
            
            # Background 模型没有 color, prompt_lang 属性，使用 name, sprite_prefix, bg_tags
            bg_info_list = [[b.name, b.sprite_prefix, b.bg_tags if b.bg_tags else ""] for b in background_list] 
            return "背景设定已加载！", bg_info_list # 修正消息
        except Exception as e:
            try:
                 background_list = self._config_manager.config.background_list # 修正列表名
                 bg_info_list = [[b.name, b.sprite_prefix, b.bg_tags if b.bg_tags else ""] for b in background_list]
            except:
                 bg_info_list = []
                 
            return f"加载失败: {str(e)}", bg_info_list
        
    # ------------------------- BGM 管理 --------------------------
    @_serialized_mutation
    def upload_bgms(
        self,
        background_name: str,
        bgm_files: List[Any],
        bgm_tags: Optional[str] = None,
    ):
        """
        上传背景音乐文件并更新背景的音乐列表和标签。

        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 所有背景音乐路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择或创建背景组！", _pd().DataFrame(), ''
        
        if not bgm_files:
            return "请选择要上传的背景音乐文件！", _pd().DataFrame(), ''
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}", _pd().DataFrame(), ''
        
        # 修正目录，使用 Background 的 prefix 和 BGM_UPLOAD_DIR
        try:
            bgm_dir = managed_project_directory(
                BGM_UPLOAD_DIR,
                background.sprite_prefix,
                root=self._project_root,
            )
        except (PermissionError, ValueError):
            return "背景音乐目录名无效！", _pd().DataFrame(), ""
        directory_was_missing = not bgm_dir.exists()
        created_directory_identity: os.stat_result | None = None
        snapshot = background.model_copy(deep=True)
        created_files: List[tuple[Path, os.stat_result]] = []
        try:
            if not hasattr(background, 'bgm_list') or background.bgm_list is None:
                background.bgm_list = []

            num_existing_bgms = len(background.bgm_list)
            bgm_tags_to_add = ''

            for i, file in enumerate(bgm_files):
                source = resolve_runtime_asset_read_path(
                    file.name,
                    root=self._project_root,
                )
                filename = safe_path_component(
                    source.name,
                    field="BGM filename",
                )
                dest_path, dest_identity = copy_file_exclusive_with_identity(
                    source,
                    bgm_dir,
                    filename,
                    field="BGM filename",
                )
                created_files.append((dest_path, dest_identity))
                if (
                    directory_was_missing
                    and created_directory_identity is None
                ):
                    created_directory_identity = bgm_dir.lstat()
                background.bgm_list.append(
                    portable_project_path(dest_path, root=self._project_root)
                )
                bgm_tags_to_add += f'音乐 {num_existing_bgms + i + 1}：\n'

            current_bgm_tags = (
                str(bgm_tags)
                if bgm_tags is not None
                else str(background.bgm_tags or "")
            )
            background.bgm_tags = current_bgm_tags + bgm_tags_to_add
            self._config_manager.save_background_config()
        except BaseException:
            _restore_model(background, snapshot)
            _unlink_created_files(created_files)
            if directory_was_missing and created_directory_identity is not None:
                try:
                    remove_empty_directory_without_links(
                        bgm_dir,
                        expected_identity=created_directory_identity,
                    )
                except (OSError, ValueError):
                    pass
            raise

        df, tags = self.load_bgms_and_tags(background_name)

        return f"成功为 {background_name} 上传 {len(bgm_files)} 个背景音乐文件！", df, tags


    @_serialized_mutation
    def delete_all_bgms(self, background_name: str) -> Tuple[str, List[str], str]:
        """
        删除背景组的所有背景音乐文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 空音乐路径列表, 空标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], ""
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}", [], ""

        directory_snapshot = _managed_directory_snapshot(
            self._project_root,
            BGM_UPLOAD_DIR,
            background.sprite_prefix,
        )
        snapshot = background.model_copy(deep=True)
        try:
            if hasattr(background, 'bgm_list'):
                background.bgm_list = []
            if hasattr(background, 'bgm_tags'):
                background.bgm_tags = ""
            self._config_manager.save_background_config()
        except BaseException:
            _restore_model(background, snapshot)
            raise

        others = [
            item
            for item in self._config_manager.config.background_list
            if item is not background
        ]
        if (
            directory_snapshot is not None
            and not _prefix_in_use(others, background.sprite_prefix)
        ):
            _remove_managed_directory(
                self._project_root,
                BGM_UPLOAD_DIR,
                background.sprite_prefix,
                expected_identity=directory_snapshot[1],
            )
        
        return f"已删除 {background_name} 的所有背景音乐！", [], ""


    @_serialized_mutation
    def upload_bgm_tags(self, background_name: str, bgm_tags: str) -> str:
        """
        上传/更新背景的音乐标签文本。
        
        Returns:
            str: 操作结果消息。
        """
        if not background_name:
            return "请先选择或创建背景组！"
        
        if not bgm_tags:
            return "请输入背景音乐标注！"
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}"
        
        snapshot = background.model_copy(deep=True)
        try:
            background.bgm_tags = bgm_tags
            self._config_manager.save_background_config()
            return "背景音乐标注成功！"
        except Exception as e:
            _restore_model(background, snapshot)
            return f"背景音乐标注出错了：{e}"


    def get_background_bgms(self, background_name: str):
        """
        获取指定背景组的所有背景音乐路径和标签。
        
        Returns:
            Tuple[List[str], str, List[Any]]: (音乐路径列表, 标签文本, 额外的返回列表 (始终为空))
        """
        if not background_name:
            return [], "", []
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        
        if not background:
            return [], "", []

        bgm_paths = getattr(background, 'bgm_list', [])
        bgm_tags = getattr(background, 'bgm_tags', "")
        
        return bgm_paths, bgm_tags, []
    
    def format_bgms_for_display(self,bgm_paths: List[str], bgm_tags: str) -> pd.DataFrame:
        """
        将 BGM 路径和标签格式化为带序号和复选框的 Dataframe。
        """
        data = []
        # 尝试解析标签（假设标签是按行与路径对应的）
        tags_list = bgm_tags.strip().split('\n') if bgm_tags else []
        
        for i, path in enumerate(bgm_paths):
            # 提取文件名
            file_name = os.path.basename(path)
            # 获取对应标签，如果标签列表不够长，则使用空字符串
            tag_line = tags_list[i] if i < len(tags_list) else ""
            # 尝试从标签行中提取实际内容（跳过 '音乐 X：' 前缀）
            tag_content = tag_line.split('：', 1)[-1].strip() if '：' in tag_line else tag_line

            data.append({
                "选择": False, # 默认不选中
                "序号": i + 1,
                "文件名": file_name,
                "路径": path,
                "标签描述": tag_content
            })
        return _pd().DataFrame(data)
    
    def load_bgms_and_tags(self, background_name: str):
        """
        根据选择的背景组加载并显示 BGM 列表和标签。
        """
        if not background_name:
            return _pd().DataFrame(), ""
            
        bgm_paths, bgm_tags, _ = self.get_background_bgms(background_name)
        
        # 将路径和标签转换为 Dataframe 格式
        bgm_dataframe = self.format_bgms_for_display(bgm_paths, bgm_tags)
        
        return bgm_dataframe, bgm_tags
    
    @_serialized_mutation
    def delete_single_bgm(self, background_name: str, bgm_index: int) -> Tuple[str, List[str], str]:
        """
        删除背景组的指定背景音乐文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 剩余音乐路径列表, 更新后的标签文本)
        """
        if not background_name:
            return "请先选择背景组！", [], ""
        
        background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
        if not background:
            return f"找不到背景组: {background_name}", [], ""
        
        bgm_list = getattr(background, 'bgm_list', [])
        bgm_tags = getattr(background, 'bgm_tags', "")

        # 索引检查
        if not bgm_list or bgm_index < 0 or bgm_index >= len(bgm_list):
            return "背景音乐不存在！", bgm_list, bgm_tags
        
        bgm_path: str = bgm_list[bgm_index]
        bgm_snapshot = _managed_file_snapshot(
            self._project_root,
            BGM_UPLOAD_DIR,
            str(bgm_path),
        ) if bgm_path else None
        
        snapshot = background.model_copy(deep=True)
        bgm_list.pop(bgm_index)
        
        # 更新标签
        new_bgm_tags = ""
        original_tags_list = bgm_tags.strip().split('\n') if bgm_tags else []
        
        if bgm_index < len(original_tags_list):
            original_tags_list.pop(bgm_index)
        
        for i, line in enumerate(original_tags_list):
            # 尝试解析并重建标签行
            parts = line.split('：') if '：' in line else line.split(':')
            current_tag = parts[-1].strip() if len(parts) > 1 else ""
            new_bgm_tags += f'音乐 {i+1}：{current_tag}\n'
        
        background.bgm_tags = new_bgm_tags
        try:
            self._config_manager.save_background_config()
        except BaseException:
            _restore_model(background, snapshot)
            raise

        if bgm_snapshot is not None and not _managed_background_path_in_use(
            self,
            str(bgm_path),
            kind="bgm",
            base_dir=BGM_UPLOAD_DIR,
        ):
            _unlink_managed_file(
                self._project_root,
                BGM_UPLOAD_DIR,
                str(bgm_path),
                expected_identity=bgm_snapshot[1],
            )
        
        return f"已删除 {background_name} 的第 {bgm_index+1} 个背景音乐文件！", bgm_list, new_bgm_tags

    def batch_delete_bgms(
        self,
        background_name: str, 
        bgm_dataframe: pd.DataFrame,
        bgm_tags 
    ) -> Tuple[str, pd.DataFrame]:
        """
        根据 Dataframe 中的复选框状态批量删除选定的背景音乐。
        """
        if not background_name:
            return "请先选择背景组！", _pd().DataFrame(), bgm_tags

        if bgm_dataframe.empty:
            return "没有音乐条可供删除。", _pd().DataFrame(), ""

        # 1. 确定要删除的索引
        try:
            # 获取 Dataframe 中 '选择' 为 True 的行
            selected_rows = bgm_dataframe[bgm_dataframe['选择'] == True]
            # 获取这些行在原始 BGM 列表中的索引 (即 '序号' - 1)
            indices_to_delete = selected_rows['序号'].tolist()
        except Exception as e:
            return f"处理数据失败: {e}", bgm_dataframe, bgm_tags

        if not indices_to_delete:
            return "请勾选要删除的音乐条。", bgm_dataframe, bgm_tags

        # 2. 批量删除（从大索引到小索引，防止删除操作改变后续索引）
        indices_to_delete.sort(reverse=True)
        
        deleted_count = 0
        message = ""

        for original_index in indices_to_delete:
            # 注意：这里的 index 是用户看到的 '序号' (从 1 开始)，需要减 1 转换为 Python 列表索引 (从 0 开始)
            list_index = original_index - 1 
            
            # 调用 Manager 的单条删除方法
            try:
                msg, remaining_paths, remaining_tags = self.delete_single_bgm(background_name, list_index)
                # 如果删除成功，则计数
                if "已删除" in msg:
                    deleted_count += 1
                else:
                    message += f"删除序号 {original_index} 失败: {msg}\n"
            except Exception as e:
                message += f"删除序号 {original_index} 发生异常: {e}\n"

        # 3. 重新加载和显示剩余的 BGM
        remaining_paths, remaining_tags, _ = self.get_background_bgms(background_name)
        new_dataframe = self.format_bgms_for_display(remaining_paths, remaining_tags)

        final_message = f"成功删除了 {deleted_count} 个音乐条。"
        if message:
            final_message += "\n部分删除失败的提示：\n" + message
            
        return final_message, new_dataframe, remaining_tags
    
    def handle_bgm_selection(self, evt: Any, bgm_dataframe: pd.DataFrame):
        """
        处理 Dataframe 行选择事件，返回选中行的路径和 Audio 组件的更新（仅 Gradio WebUI 使用）。
        
        evt 在 Gradio 下为 gr.SelectData；Qt 设置端不调用本方法。

        Returns:
            Tuple[str, str]: (操作消息, 供 Audio 播放的本地路径)
        """
        if evt is None or evt.index is None:
            return "请点击 Dataframe 中的一行。", ""
        
        # 获取点击的行索引 (evt.index 是 (row_index, col_index))
        row_index = evt.index[0]
        
        if row_index < 0 or row_index >= len(bgm_dataframe):
            return "无效的行选择。", ""
        
        # 从 Dataframe 中取出选中行对应的文件路径
        # 假设 '路径' 是 Dataframe 中的一列
        try:
            selected_path = bgm_dataframe.iloc[row_index]['路径']
            try:
                resolved = resolve_runtime_asset_path(
                    str(selected_path or ""),
                    root=self._project_root,
                )
                if not resolved.is_file():
                    raise FileNotFoundError(resolved)
            except (OSError, PermissionError, RuntimeError, ValueError):
                return f"文件路径不存在: {selected_path}", ""
            selected_path = resolved.as_posix()
            file_name = resolved.name
            
            # 返回更新后的 Audio 组件
            return (
                f"正在播放: {file_name}", 
                selected_path
            )
            
        except KeyError:
            return "Dataframe 缺少 '路径' 列，无法播放。", ""
        except Exception as e:
            return f"播放出错: {e}", ""
        

    def export_background_file(self, background_name: str) -> str:
        """导出指定背景组到 .bg 文件"""
        try:
            background: Optional[Background] = self._config_manager.get_background_by_name(background_name)
            if not background:
                return f"找不到背景组: {background_name}"

            filename = safe_path_component(
                f"{background_name}.bg",
                field="background export filename",
            )
            output = self._project_root / "output" / filename
            fu.export_background(
                [background],
                output.as_posix(),
                project_root=self._project_root,
            )
            return f"背景组已导出到: {output}"
        except Exception as e:
            return f"背景导出失败: {e}"
    def import_background_file(self, input_path: str):
        """从 .bg 文件导入背景配置"""
        existing_configs = self._config_manager.config.background_list
        previous_configs = list(existing_configs)
        try:
            with fu.package_import_transaction() as transaction_paths:
                new_configs = fu.import_background(
                    input_path,
                    existing_configs,
                    project_root=self._project_root,
                    transaction_paths=transaction_paths,
                )

                # 将导入的配置合并到现有配置中
                # 注意：import_background 已经处理了冲突，这里只需要追加
                for config in new_configs:
                    # 检查是否因为冲突被重命名，如果 name 已在 existing_configs 中，则说明是 import 函数解决的冲突
                    if config not in existing_configs:
                        existing_configs.append(config)

                self._config_manager.save_background_config()
            
            # 刷新显示列表 (与 load_backgrounds_from_file 类似)
            bg_name_list = [b.name for b in existing_configs]
            
            return f"成功导入 {len(new_configs)} 个背景组！", bg_name_list
        except Exception as e:
            existing_configs[:] = previous_configs
            # 刷新显示列表
            bg_name_list = [b.name for b in self._config_manager.config.background_list]
            return f"背景导入失败: {e}", bg_name_list

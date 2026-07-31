import hashlib
import os
import re
from copy import deepcopy
from functools import wraps
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import List, Dict, Any, Tuple, Optional, Union
from config.schema import Character, Sprite
from config.config_manager import ConfigManager
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
    resolve_runtime_asset_read_path,
    safe_path_component,
    safe_path_component_with_suffix,
)

UPLOAD_DIR = "data/sprite"
VOICE_DIR = "data/speech"
MODEL_DIR = "data/models"

_CHARACTER_IO_LOCK = RLock()


def _serialized_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _CHARACTER_IO_LOCK:
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


def _sprite_field(sprite_data: Union[Sprite, dict], key: str, default: Any = "") -> Any:
    if isinstance(sprite_data, Sprite):
        return getattr(sprite_data, key, default)
    return sprite_data.get(key, default)


def _voice_filename_for_sprite(sprite_data: Union[Sprite, dict], sprite_index: int, file_ext: str) -> str:
    sprite_path = str(_sprite_field(sprite_data, "path", "") or "")
    portable_sprite_path = sprite_path.replace("\\", "/")
    sprite_stem = PurePosixPath(portable_sprite_path).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", sprite_stem).strip("._-")
    if not safe_stem:
        safe_stem = f"sprite_{sprite_index:02d}"
    digest_source = portable_sprite_path or safe_stem or str(sprite_index)
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    return safe_path_component_with_suffix(
        f"voice_{safe_stem}",
        f"_{digest}{file_ext}",
        field="voice filename",
    )


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


def _prefix_in_use(characters: List[Character], prefix: str) -> bool:
    key = _prefix_key(prefix)
    return bool(key) and any(
        _prefix_key(character.sprite_prefix) == key
        for character in characters
    )


def _prefix_key(value: Any) -> str:
    raw = str(value or "")
    try:
        return portable_name_key(safe_path_component(raw, field="sprite_prefix"))
    except ValueError:
        return ""


def _managed_sprite_path_in_use(
    manager: "CharacterManager",
    raw_path: str,
    *,
    field: str,
    base_dir: str,
) -> bool:
    try:
        target = managed_project_file(raw_path, base_dir, root=manager._project_root)
    except (OSError, PermissionError, ValueError):
        return False
    if target is None:
        return False
    for character in manager._config_manager.config.characters:
        for sprite in character.sprites or []:
            candidate_raw = str(_sprite_field(sprite, field, "") or "")
            try:
                candidate = managed_project_file(
                    candidate_raw,
                    base_dir,
                    root=manager._project_root,
                )
            except (OSError, PermissionError, ValueError):
                continue
            if candidate == target:
                return True
    return False


class CharacterManager:
    """
    负责角色配置、立绘和语音资源的管理。
    内部使用 ConfigManager 来持久化数据。
    """

    _config_manager: ConfigManager
    
    def __init__(self):
        """初始化 CharacterManager，获取 ConfigManager 单例。"""
        self._config_manager = ConfigManager()
        self._project_root = project_root()

    def _get_characters(self) -> List[Character]:
        """获取当前的 Character 列表"""
        try:
            return self._config_manager.config.characters
        except Exception:
            # 如果配置未加载或失败，返回空列表
            return []
    def get_character_name_list(self):
        return [c.name for c in self._config_manager.config.characters]

    def _save_characters_config(self) -> None:
        """保存角色配置的便捷方法"""
        self._config_manager.save_characters_config()

    def save_characters_to_file(self) -> str:
        """
        保存所有角色配置到文件。
        
        Returns:
            str: 操作结果消息。
        """
        try:
            self._save_characters_config()
            return f"人物设定已保存到 {self._config_manager._CHARACTERS_CONFIG_PATH}！"
        except Exception as e:
            return f"保存失败: {str(e)}"


    @_serialized_mutation
    def add_character(self, name: str, color: str, sprite_prefix: str, gpt_model_path: str,
                     sovits_model_path: str, refer_audio_path: str, prompt_text: str,
                     prompt_lang: str, character_setting: str,
                     speech_speed: float = 1.0,
                     speech_volume: float = 1.0,
                     pronunciation_map: dict = None,
                     edit_as_name: Optional[str] = None,
                     emotion_tags: Optional[str] = None) -> Tuple[str, List[str]]:
        """
        添加或更新角色配置。

        若 edit_as_name 为当前列表中已存在的名字（如 UI 下拉当前选中项），
        则按该条记录做更新；名称栏改为新名字时视为重命名，不会新建另一条角色。

        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有角色名称列表)
        """
        current_names = [c.name for c in self._get_characters()]
        if not name:
            return "名称不能为空！", current_names

        characters = self._config_manager.config.characters

        # check sprite_prefix collision (unique per-character upload directory)
        edit_target_name = str(edit_as_name or "").strip()
        _prefix = str(sprite_prefix or "")
        if _prefix:
            try:
                _prefix = safe_path_component(_prefix, field="sprite_prefix")
            except ValueError:
                return "立绘目录名无效！", current_names
            sprite_prefix = _prefix
            prefix_key = portable_name_key(_prefix)
            for c in characters:
                _c_prefix_key = _prefix_key(c.sprite_prefix)
                if not _c_prefix_key or prefix_key != _c_prefix_key:
                    continue
                # editing: new prefix must not collide with *other* characters
                if edit_target_name:
                    if c.name.casefold() != edit_target_name.casefold():
                        return (
                            f"立绘目录名「{_prefix}」已被角色「{c.name}」占用！",
                            current_names,
                        )
                else:
                    return (
                        f"立绘目录名「{_prefix}」已被角色「{c.name}」占用！",
                        current_names,
                    )

        if edit_target_name:
            target = self._config_manager.get_character_by_name(edit_target_name)
            if target is not None:
                old_prefix = str(target.sprite_prefix or "")
                if old_prefix and old_prefix != str(sprite_prefix or ""):
                    return (
                        "人物资源目录创建后不可直接修改；请新建人物后迁移资源。",
                        [c.name for c in characters],
                    )
                taken = self._config_manager.get_character_by_name(name)
                if taken is not None and taken is not target:
                    return f"名称「{name}」已与其他角色重复！", [c.name for c in characters]
                snapshot = target.model_copy(deep=True)
                try:
                    target.name = name
                    target.color = color
                    target.sprite_prefix = sprite_prefix
                    target.gpt_model_path = gpt_model_path
                    target.sovits_model_path = sovits_model_path
                    target.prompt_text = prompt_text
                    target.prompt_lang = prompt_lang
                    target.refer_audio_path = refer_audio_path
                    target.character_setting = character_setting
                    target.speech_speed = speech_speed
                    target.speech_volume = speech_volume
                    if pronunciation_map is not None:
                        target.pronunciation_map = pronunciation_map
                    if emotion_tags is not None:
                        target.emotion_tags = emotion_tags
                    self._save_characters_config()
                except BaseException:
                    _restore_model(target, snapshot)
                    raise
                return "人物已更新！", [c.name for c in characters]

        existing_character: Optional[Character] = self._config_manager.get_character_by_name(name)
        
        if existing_character is None:
            # 创建新的 Character 实例
            new_character = Character(
                name=name,
                color=color,
                sprite_prefix=sprite_prefix,
                gpt_model_path=gpt_model_path,
                sovits_model_path=sovits_model_path,
                refer_audio_path=refer_audio_path,
                prompt_text=prompt_text,
                prompt_lang=prompt_lang,
                sprites=[],
                sprite_scale=1.0,
                emotion_tags=emotion_tags or "",
                character_setting=character_setting,
                speech_speed=speech_speed,
                speech_volume=speech_volume,
                pronunciation_map=pronunciation_map or {},
            )
            characters.append(new_character)
            try:
                self._save_characters_config()
            except BaseException:
                if characters and characters[-1] is new_character:
                    characters.pop()
                else:
                    try:
                        characters.remove(new_character)
                    except ValueError:
                        pass
                raise
            return "人物已添加！", [c.name for c in characters]
        else:
            # 更新现有 Character 实例的属性
            old_prefix = str(existing_character.sprite_prefix or "")
            if old_prefix and old_prefix != str(sprite_prefix or ""):
                return (
                    "人物资源目录创建后不可直接修改；请新建人物后迁移资源。",
                    [c.name for c in characters],
                )
            snapshot = existing_character.model_copy(deep=True)
            try:
                existing_character.name = name
                existing_character.color = color
                existing_character.sprite_prefix = sprite_prefix
                existing_character.gpt_model_path = gpt_model_path
                existing_character.sovits_model_path = sovits_model_path
                existing_character.prompt_text = prompt_text
                existing_character.prompt_lang = prompt_lang
                existing_character.refer_audio_path = refer_audio_path
                existing_character.character_setting = character_setting
                existing_character.speech_speed = speech_speed
                existing_character.speech_volume = speech_volume
                if pronunciation_map is not None:
                    existing_character.pronunciation_map = pronunciation_map
                if emotion_tags is not None:
                    existing_character.emotion_tags = emotion_tags
                self._save_characters_config()
            except BaseException:
                _restore_model(existing_character, snapshot)
                raise
            return "人物已更新！", [c.name for c in characters]


    @_serialized_mutation
    def delete_character(self, name: str) -> Tuple[str, List[str]]:
        """
        删除角色及其相关文件。
        
        Returns:
            Tuple[str, List[str]]: (操作结果消息, 当前所有角色名称列表)
        """
        characters = self._config_manager.config.characters
        current_names = [c.name for c in characters]
        
        if not name or name == "新角色":
            return "请选择要删除的角色！", current_names
        
        character_to_delete: Optional[Character] = self._config_manager.get_character_by_name(name)
        
        if character_to_delete is None:
            return f"找不到角色: {name}", current_names

        sprite_prefix = character_to_delete.sprite_prefix
        directory_snapshots = {
            base_dir: _managed_directory_snapshot(
                self._project_root,
                base_dir,
                sprite_prefix,
            )
            for base_dir in (UPLOAD_DIR, VOICE_DIR, MODEL_DIR)
        } if sprite_prefix else {}

        # 先提交引用删除，再做最佳努力的磁盘清理；保存失败时恢复原顺序。
        original_index = characters.index(character_to_delete)
        try:
            characters.remove(character_to_delete)
        except ValueError:
            return f"找不到角色: {name}", current_names
        try:
            self._save_characters_config()
        except BaseException:
            characters.insert(original_index, character_to_delete)
            raise
        new_names = [c.name for c in characters]

        if not sprite_prefix:
            return "已删除角色", new_names
        
        # 旧配置可能存在重复 prefix；只要仍被引用，就不清理共享目录。
        if not _prefix_in_use(characters, sprite_prefix):
            for base_dir in [UPLOAD_DIR, VOICE_DIR, MODEL_DIR]:
                snapshot = directory_snapshots.get(base_dir)
                if snapshot is not None:
                    _remove_managed_directory(
                        self._project_root,
                        base_dir,
                        sprite_prefix,
                        expected_identity=snapshot[1],
                    )
        
        return f"角色 {name} 已删除！", new_names


    def update_character_options(self):
        """
        返回用于 Gradio CheckboxGroup 的选项列表。
        
        Returns:
            gr.CheckboxGroup: Gradio 组件的配置（假设）或选项列表。
        """
        try:
            import gradio as gr 
            choices = [c.name for c in self._get_characters()]
            return gr.CheckboxGroup(choices=choices)
        except ImportError:
            return [c.name for c in self._get_characters()]


    @_serialized_mutation
    def upload_sprites(self, character_name: str, sprite_files: List[Any], emotion_tags: str) -> Tuple[str, List[str], str]:
        """
        上传立绘文件并更新角色的立绘列表和情绪标签。

        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 所有立绘路径列表, 更新后的情绪标签文本)
        """
        if not character_name:
            return "请先选择或创建角色！", [], ''
        
        if not sprite_files:
            return "请选择要上传的图片！", [], ''
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", [], ''
        
        try:
            char_dir = managed_project_directory(
                UPLOAD_DIR,
                character.sprite_prefix,
                root=self._project_root,
            )
        except (PermissionError, ValueError):
            return "立绘目录名无效！", [], emotion_tags
        directory_was_missing = not char_dir.exists()
        created_directory_identity: os.stat_result | None = None
        snapshot = character.model_copy(deep=True)
        created_files: List[tuple[Path, os.stat_result]] = []
        try:
            if character.sprites is None:
                character.sprites = []

            num_existing_sprites = len(character.sprites)
            emotion_tags_to_add = ''

            for i, file in enumerate(sprite_files):
                source = resolve_runtime_asset_read_path(
                    file.name,
                    root=self._project_root,
                )
                filename = safe_path_component(
                    source.name,
                    field="sprite filename",
                )
                dest_path, dest_identity = copy_file_exclusive_with_identity(
                    source,
                    char_dir,
                    filename,
                    field="sprite filename",
                )
                created_files.append((dest_path, dest_identity))
                if (
                    directory_was_missing
                    and created_directory_identity is None
                ):
                    created_directory_identity = char_dir.lstat()
                stored_path = portable_project_path(dest_path, root=self._project_root)

                character.sprites.append({"path": stored_path})
                emotion_tags_to_add += f'立绘 {num_existing_sprites + i + 1}：\n'

            current_emotion_tags = character.emotion_tags if character.emotion_tags else ""
            character.emotion_tags = current_emotion_tags + emotion_tags_to_add
            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            _unlink_created_files(created_files)
            if directory_was_missing and created_directory_identity is not None:
                try:
                    remove_empty_directory_without_links(
                        char_dir,
                        expected_identity=created_directory_identity,
                    )
                except (OSError, ValueError):
                    pass
            raise

        all_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites]
        return f"成功为 {character_name} 上传 {len(sprite_files)} 张立绘！", all_sprite_paths, character.emotion_tags


    @_serialized_mutation
    def delete_all_sprites(self, character_name: str) -> Tuple[str, List[str], str]:
        """
        删除角色的所有立绘及其语音文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 空立绘路径列表, 空情绪标签文本)
        """
        if not character_name:
            return "请先选择角色！", [], ""
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", [], ""

        directory_snapshots = {
            base_dir: _managed_directory_snapshot(
                self._project_root,
                base_dir,
                character.sprite_prefix,
            )
            for base_dir in (UPLOAD_DIR, VOICE_DIR)
        }
        snapshot = character.model_copy(deep=True)
        try:
            character.sprites = []
            character.emotion_tags = ""
            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            raise

        other_characters = [
            item
            for item in self._config_manager.config.characters
            if item is not character
        ]
        if not _prefix_in_use(other_characters, character.sprite_prefix):
            for base_dir in (UPLOAD_DIR, VOICE_DIR):
                directory_snapshot = directory_snapshots.get(base_dir)
                if directory_snapshot is not None:
                    _remove_managed_directory(
                        self._project_root,
                        base_dir,
                        character.sprite_prefix,
                        expected_identity=directory_snapshot[1],
                    )
        
        return f"已删除 {character_name} 的所有立绘！", [], ""


    @_serialized_mutation
    def delete_single_sprite(self, character_name: str, sprite_index: int) -> Tuple[str, List[str], str]:
        """
        删除角色的指定立绘及其语音文件。
        
        Returns:
            Tuple[str, List[str], str]: (操作结果消息, 剩余立绘路径列表, 更新后的情绪标签文本)
        """
        if not character_name:
            return "请先选择角色！", [], ""
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", [], ""
        
        # 索引检查
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            remaining_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites]
            return "立绘不存在！", remaining_paths, character.emotion_tags
        
        sprite_data: Union[Sprite, dict] = character.sprites[sprite_index]
        
        # 获取路径
        sprite_path = sprite_data.path if isinstance(sprite_data, Sprite) else sprite_data.get("path", "")
        voice_path = sprite_data.voice_path if isinstance(sprite_data, Sprite) else sprite_data.get("voice_path", "")
        sprite_snapshot = _managed_file_snapshot(
            self._project_root,
            UPLOAD_DIR,
            str(sprite_path),
        ) if sprite_path else None
        voice_snapshot = _managed_file_snapshot(
            self._project_root,
            VOICE_DIR,
            str(voice_path),
        ) if voice_path else None

        snapshot = character.model_copy(deep=True)
        character.sprites.pop(sprite_index)
        
        # 更新情绪标签
        emotion_tags = ""
        original_tags_list = character.emotion_tags.strip().split('\n') if character.emotion_tags else []
        
        if sprite_index < len(original_tags_list):
            original_tags_list.pop(sprite_index)
        
        for i, line in enumerate(original_tags_list):
            parts = line.split('：') if '：' in line else line.split(':')
            current_tag = parts[-1].strip() if len(parts) > 1 else ""
            emotion_tags += f'立绘 {i+1}：{current_tag}\n'
            
        character.emotion_tags = emotion_tags
        try:
            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            raise

        if sprite_snapshot is not None and not _managed_sprite_path_in_use(
            self,
            str(sprite_path),
            field="path",
            base_dir=UPLOAD_DIR,
        ):
            _unlink_managed_file(
                self._project_root,
                UPLOAD_DIR,
                str(sprite_path),
                expected_identity=(
                    sprite_snapshot[1]
                    if sprite_snapshot is not None
                    else None
                ),
            )
        if voice_snapshot is not None and not _managed_sprite_path_in_use(
            self,
            str(voice_path),
            field="voice_path",
            base_dir=VOICE_DIR,
        ):
            _unlink_managed_file(
                self._project_root,
                VOICE_DIR,
                str(voice_path),
                expected_identity=(
                    voice_snapshot[1]
                    if voice_snapshot is not None
                    else None
                ),
            )
        
        remaining_sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites]
        return f"已删除 {character_name} 的第 {sprite_index+1} 张立绘！", remaining_sprite_paths, emotion_tags


    @_serialized_mutation
    def upload_emotion_tags(self, character_name: str, emotion_tags: str) -> str:
        """
        上传/更新角色的情绪标签文本。
        
        Returns:
            str: 操作结果消息。
        """
        if not character_name:
            return "请先选择或创建角色！"
        
        if not emotion_tags: # 假设原始代码中的 emotion_inputs 应该被 emotion_tags 取代
            return "请输入情绪标注！"
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}"
        
        snapshot = character.model_copy(deep=True)
        try:
            character.emotion_tags = emotion_tags
            self._config_manager.save_characters_config()
            return "标注成功！"
        except Exception as e:
            _restore_model(character, snapshot)
            return f"标注出错了：{e}"


    @_serialized_mutation
    def upload_voice(self, character_name: str, sprite_index: int, voice_file: str, voice_text: str, voice_type: str = "") -> Tuple[str, Optional[str]]:
        """
        为指定立绘上传语音文件。
        
        Returns:
            Tuple[str, Optional[str]]: (操作结果消息, 语音文件路径或 None)
        """
        if not character_name:
            return "请先选择角色！", None
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}", None
        
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return "立绘不存在！", None
        
        sprite_data: Union[Sprite, dict] = character.sprites[sprite_index]
        original_voice_path = str(_sprite_field(sprite_data, "voice_path", "") or "")
        original_voice_snapshot = _managed_file_snapshot(
            self._project_root,
            VOICE_DIR,
            original_voice_path,
        ) if original_voice_path else None
        
        if (not voice_file) and (not original_voice_path):
            return "请选择语音文件！", None
        
        snapshot = character.model_copy(deep=True)
        created_voice_path: Path | None = None
        created_voice_identity: os.stat_result | None = None
        voice_char_dir: Path | None = None
        directory_was_missing = False
        created_directory_identity: os.stat_result | None = None
        try:
            if voice_file:
                try:
                    voice_char_dir = managed_project_directory(
                        VOICE_DIR,
                        character.sprite_prefix,
                        root=self._project_root,
                    )
                except (PermissionError, ValueError):
                    return "语音目录名无效！", None
                directory_was_missing = not voice_char_dir.exists()
                source_voice = resolve_runtime_asset_read_path(
                    voice_file,
                    root=self._project_root,
                )
                file_ext = source_voice.suffix
                voice_filename = _voice_filename_for_sprite(sprite_data, sprite_index, file_ext)
                (
                    created_voice_path,
                    created_voice_identity,
                ) = copy_file_exclusive_with_identity(
                    source_voice,
                    voice_char_dir,
                    voice_filename,
                    field="voice filename",
                )
                if directory_was_missing:
                    created_directory_identity = voice_char_dir.lstat()
                stored_voice_path = portable_project_path(
                    created_voice_path,
                    root=self._project_root,
                )
            else:
                stored_voice_path = original_voice_path

            if isinstance(sprite_data, Sprite):
                sprite_data.voice_path = stored_voice_path
                sprite_data.voice_text = voice_text
                if voice_type:
                    sprite_data.voice_type = voice_type
            else:
                character.sprites[sprite_index]["voice_path"] = stored_voice_path
                character.sprites[sprite_index]["voice_text"] = voice_text
                if voice_type:
                    character.sprites[sprite_index]["voice_type"] = voice_type

            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            if (
                created_voice_path is not None
                and created_voice_identity is not None
            ):
                _unlink_created_files(
                    [(created_voice_path, created_voice_identity)]
                )
            if (
                directory_was_missing
                and voice_char_dir is not None
                and created_directory_identity is not None
            ):
                try:
                    remove_empty_directory_without_links(
                        voice_char_dir,
                        expected_identity=created_directory_identity,
                    )
                except (OSError, ValueError):
                    pass
            raise

        if (
            created_voice_path is not None
            and original_voice_snapshot is not None
            and not _managed_sprite_path_in_use(
                self,
                original_voice_path,
                field="voice_path",
                base_dir=VOICE_DIR,
            )
        ):
            _unlink_managed_file(
                self._project_root,
                VOICE_DIR,
                original_voice_path,
                expected_identity=(
                    original_voice_snapshot[1]
                    if original_voice_snapshot is not None
                    else None
                ),
            )
        
        return f"语音已上传到立绘 {sprite_index+1}！", stored_voice_path


    def get_sprite_voice(self, character_name: str, sprite_index: int) -> Tuple[Optional[str], str]:
        """
        获取指定立绘的语音路径和文本。
        
        Returns:
            Tuple[Optional[str], str]: (语音文件路径或 None, 语音文本内容)
        """
        if not character_name or sprite_index is None:
            return None, ""
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        
        if not character or not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return None, ""
        
        sprite_data: Union[Sprite, dict] = character.sprites[sprite_index]
        
        if isinstance(sprite_data, Sprite):
            voice_path = sprite_data.voice_path
            voice_text = sprite_data.voice_text if sprite_data.voice_text else ""
        else:
            voice_path = sprite_data.get("voice_path", None)
            voice_text = sprite_data.get("voice_text", "")

        return voice_path, voice_text

    @_serialized_mutation
    def save_sprite_voice_text(self, character_name: str, sprite_index: int, voice_text: str) -> str:
        """单独保存立绘的语音文字，不需要重新上传音频。"""
        if not character_name:
            return "请先选择角色！"
        character = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}"
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return "立绘不存在！"

        snapshot = character.model_copy(deep=True)
        try:
            sprite_data = character.sprites[sprite_index]
            if isinstance(sprite_data, Sprite):
                sprite_data.voice_text = voice_text if voice_text else None
            else:
                sprite_data["voice_text"] = voice_text if voice_text else None
            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            raise
        return "语音文字已保存"

    @_serialized_mutation
    def save_sprite_voice_type(self, character_name: str, sprite_index: int, voice_type: str) -> str:
        """单独保存立绘的语音类型（preset/reference），不需要重新上传音频。"""
        if not character_name:
            return "请先选择角色！"
        character = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}"
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return "立绘不存在！"

        snapshot = character.model_copy(deep=True)
        try:
            sprite_data = character.sprites[sprite_index]
            if isinstance(sprite_data, Sprite):
                sprite_data.voice_type = voice_type if voice_type else None
            else:
                sprite_data["voice_type"] = voice_type if voice_type else None
            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            raise
        return "语音类型已保存"

    @_serialized_mutation
    def delete_sprite_voice(self, character_name: str, sprite_index: int) -> str:
        """删除指定立绘的语音文件和引用。"""
        if not character_name:
            return "请先选择角色！"
        character = self._config_manager.get_character_by_name(character_name)
        if not character:
            return f"找不到角色: {character_name}"
        if not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
            return "立绘不存在！"

        sprite_data = character.sprites[sprite_index]
        existing_voice_path = str(
            _sprite_field(sprite_data, "voice_path", "") or ""
        )
        voice_snapshot = _managed_file_snapshot(
            self._project_root,
            VOICE_DIR,
            existing_voice_path,
        ) if existing_voice_path else None
        snapshot = character.model_copy(deep=True)
        try:
            if isinstance(sprite_data, Sprite):
                voice_path = sprite_data.voice_path
                sprite_data.voice_path = None
                sprite_data.voice_text = None
            else:
                voice_path = sprite_data.get("voice_path", None)
                sprite_data["voice_path"] = None
                sprite_data["voice_text"] = None
            self._config_manager.save_characters_config()
        except BaseException:
            _restore_model(character, snapshot)
            raise

        if voice_snapshot is not None and not _managed_sprite_path_in_use(
            self,
            str(voice_path),
            field="voice_path",
            base_dir=VOICE_DIR,
        ):
            _unlink_managed_file(
                self._project_root,
                VOICE_DIR,
                str(voice_path),
                expected_identity=voice_snapshot[1],
            )

        return f"已删除立绘 {sprite_index + 1} 的语音"

    def get_character_sprites(self, character_name: str) -> Tuple[List[str], str, List[Any]]:
        """
        获取指定角色的所有立绘路径和情绪标签。
        
        Returns:
            Tuple[List[str], str, List[Any]]: (立绘路径列表, 情绪标签文本, 额外的返回列表 (始终为空))
        """
        if not character_name:
            return [], "", []
        
        character: Optional[Character] = self._config_manager.get_character_by_name(character_name)
        
        if not character:
            return [], "", []

        sprite_paths = [s.path if isinstance(s, Sprite) else s.get('path', '') for s in character.sprites if s]
        emotion_tags = character.emotion_tags if character.emotion_tags else ""
        
        return sprite_paths, emotion_tags, []


    @_serialized_mutation
    def save_sprite_scale(self, name: str, scale: float) -> str:
        """
        保存角色的立绘缩放比例。
        
        Returns:
            str: 操作结果消息。
        """
        if not name:
            return "名称不能为空！", [c.name for c in self._get_characters()]
            
        character: Optional[Character] = self._config_manager.get_character_by_name(name)

        if character:
            snapshot = character.model_copy(deep=True)
            try:
                character.sprite_scale = scale
                self._config_manager.save_characters_config()
            except BaseException:
                _restore_model(character, snapshot)
                raise
            return "保存立绘缩放倍率成功"
        
        return f"找不到角色: {name}"


    def load_characters_from_file(self) -> Tuple[str, List[List[str]]]:
        """
        重新加载人物设定文件。
        
        Returns:
            Tuple[str, List[List[str]]]: (操作结果消息, 角色信息列表: [[name, color, prompt_lang], ...])
        """
        try:
            self._config_manager.reload()
            characters = self._config_manager.config.characters
            
            char_info_list = [[c.name, c.color, c.prompt_lang if c.prompt_lang else ""] for c in characters]
            return "人物设定已加载！", char_info_list
        except Exception as e:
            try:
                 characters = self._config_manager.config.characters
                 char_info_list = [[c.name, c.color, c.prompt_lang if c.prompt_lang else ""] for c in characters]
            except:
                 char_info_list = []
                 
            return f"加载失败: {str(e)}", char_info_list

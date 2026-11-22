"""Thin compatibility facade delegating character mutations to ``config.character_ops``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, List, Optional, Tuple, Union

from config.character_ops import (
    CharacterProfileError, ConfigManagerCharacterTarget, clamp_portrait_sprite_index,
    delete_all_character_sprites, delete_character_and_assets, delete_character_sprite_voice,
    delete_single_character_sprite, get_character_sprite_voice, parse_relation_graph,
    rename_relation_graph_owner, resolve_mutable_character, save_character_avatar_bank,
    save_character_emotion_tags_op, save_character_patch, save_character_sprite_groups,
    save_character_sprite_mouths, save_character_sprite_scale_op, save_character_sprite_transitions,
    save_character_sprite_voice_text, save_character_sprite_voice_type, update_character_relation_graph,
    upload_character_sprite_voice, upload_character_sprites, voice_filename_for_sprite,
)
from config.config_manager import ConfigManager
from config.schema import Character, ModelSprites, RelationGraph, Sprite

UPLOAD_DIR = "data/sprite"
VOICE_DIR = "data/speech"
MODEL_DIR = "data/models"
CHARACTER_CONFIG_PATH = ConfigManager._CHARACTERS_CONFIG_PATH
_voice_filename_for_sprite = voice_filename_for_sprite


class CharacterManager:
    """Compatibility facade over ``ConfigManager`` and ``config.character_ops``."""

    _config_manager: ConfigManager

    def __init__(self) -> None:
        self._config_manager = ConfigManager()

    def _target(self) -> ConfigManagerCharacterTarget:
        return ConfigManagerCharacterTarget(
            self._config_manager, save_fn=self._save_characters_config,
            custom_save="_save_characters_config" in getattr(self, "__dict__", {}),
        )

    def _get_characters(self) -> List[Character]:
        try:
            return self._config_manager.config.characters
        except Exception:
            return []

    def get_character_name_list(self) -> List[str]:
        return [c.name for c in self._config_manager.config.characters]

    def _save_characters_config(self) -> None:
        self._config_manager.save_characters_config()

    def save_avatar_bank(self, name: str, avatar_type: str, bank: ModelSprites, *, activate: bool = False) -> None:
        save_character_avatar_bank(self._target(), name, avatar_type, bank, activate=activate)

    def save_characters_to_file(self) -> str:
        try:
            self._save_characters_config()
            return f"人物设定已保存到 {CHARACTER_CONFIG_PATH}！"
        except Exception as exc:
            return f"保存失败: {exc}"

    def save_sprite_mouths(self, name: str, results: list[tuple[int, str, str | None]]) -> None:
        save_character_sprite_mouths(self._target(), name, results)

    def save_sprite_transitions(self, name: str, results: list[dict[str, Any]]) -> None:
        save_character_sprite_transitions(self._target(), name, results, upload_dir=UPLOAD_DIR)

    @staticmethod
    def _clamp_portrait_sprite_index(value: Any, sprite_count: int) -> int:
        return clamp_portrait_sprite_index(value, sprite_count)

    def _resolve_mutable_character(self, name: str) -> Optional[Character]:
        return resolve_mutable_character(self._target(), name)

    def save_character_patch(
        self,
        patch: Mapping[str, Any],
        *,
        original_name: Optional[str] = None,
        target_id: Optional[str] = None,
        sprite_portrait_crops: Optional[Mapping[int, Any]] = None,
        sprite_group_map: Optional[Mapping[int, Optional[str]]] = None,
    ) -> tuple[Character, str | None, bool]:
        """Validate and apply a partial or full character patch without per-field parameters."""
        return save_character_patch(
            self._target(), patch, original_name=original_name, target_id=target_id,
            sprite_portrait_crops=sprite_portrait_crops, sprite_group_map=sprite_group_map,
        )

    def add_character(
        self,
        name: str,
        color: str,
        sprite_prefix: str,
        gpt_model_path: str = "",
        sovits_model_path: str = "",
        refer_audio_path: str = "",
        prompt_text: str = "",
        prompt_lang: str = "",
        character_setting: str = "",
        speech_speed: float = 1.0,
        speech_volume: float = 1.0,
        pronunciation_map: Optional[dict[str, str]] = None,
        edit_as_name: Optional[str] = None,
        emotion_tags: Optional[str] = None,
        character_brief: Optional[str] = None,
        avatar_type: Optional[str] = None,
        avatars: Optional[dict[str, Union[ModelSprites, dict[str, Any]]]] = None,
        portrait_crop: Any = None,
        portrait_sprite_index: Optional[int] = None,
        sprite_portrait_crops: Optional[dict[int, Any]] = None,
        relation_graph: Optional[Union[RelationGraph, dict[str, Any]]] = None,
        sprite_groups: Optional[List[str]] = None,
        default_sprite_group: Optional[str] = None,
        fallback_to_default_group: Optional[bool] = None,
        sprite_group_map: Optional[dict[int, Optional[str]]] = None,
        display_name: Optional[str] = None,
        **extra_fields: Any,
    ) -> Tuple[str, List[str]]:
        """Legacy positional/keyword upsert wrapper retained for compatibility."""
        patch: dict[str, Any] = {
            **extra_fields, "name": name, "color": color, "sprite_prefix": sprite_prefix,
            "gpt_model_path": gpt_model_path, "sovits_model_path": sovits_model_path,
            "refer_audio_path": refer_audio_path, "prompt_text": prompt_text,
            "prompt_lang": prompt_lang, "character_setting": character_setting,
            "speech_speed": speech_speed, "speech_volume": speech_volume,
        }
        optional = {
            "pronunciation_map": pronunciation_map, "emotion_tags": emotion_tags,
            "character_brief": character_brief, "avatar_type": avatar_type, "avatars": avatars,
            "portrait_crop": portrait_crop, "portrait_sprite_index": portrait_sprite_index,
            "relation_graph": relation_graph, "sprite_groups": sprite_groups,
            "default_sprite_group": default_sprite_group,
            "fallback_to_default_group": fallback_to_default_group, "display_name": display_name,
        }
        for key, value in optional.items():
            if value is not None:
                patch[key] = value
        try:
            _saved, _renamed, created = self.save_character_patch(
                patch, original_name=edit_as_name,
                sprite_portrait_crops=sprite_portrait_crops, sprite_group_map=sprite_group_map,
            )
        except CharacterProfileError as exc:
            return str(exc), [c.name for c in self._get_characters()]
        return ("人物已添加！" if created else "人物已更新！", [c.name for c in self._get_characters()])

    def delete_character(self, name: str) -> Tuple[str, List[str]]:
        return delete_character_and_assets(self._target(), name, upload_dir=UPLOAD_DIR, voice_dir=VOICE_DIR, model_dir=MODEL_DIR)

    def update_character_options(self) -> Any:
        try:
            import gradio as gr
            return gr.CheckboxGroup(choices=[c.name for c in self._get_characters()])
        except ImportError:
            return [c.name for c in self._get_characters()]

    def upload_sprites(self, character_name: str, sprite_files: List[Any], emotion_tags: str, **kwargs: Any) -> Tuple[str, List[str], str]:
        return upload_character_sprites(self._target(), character_name, sprite_files, emotion_tags, upload_dir=UPLOAD_DIR, **kwargs)

    def delete_all_sprites(self, character_name: str) -> Tuple[str, List[str], str]:
        return delete_all_character_sprites(self._target(), character_name, upload_dir=UPLOAD_DIR, voice_dir=VOICE_DIR)

    def delete_single_sprite(self, character_name: str, sprite_index: int) -> Tuple[str, List[str], str]:
        return delete_single_character_sprite(self._target(), character_name, sprite_index)

    def upload_emotion_tags(self, character_name: str, emotion_tags: str) -> str:
        try:
            save_character_emotion_tags_op(self._target(), character_name, emotion_tags)
            return "标注成功！"
        except CharacterProfileError as exc:
            return str(exc)
        except Exception as exc:
            return f"标注出错了：{exc}"

    def upload_voice(self, character_name: str, sprite_index: int, voice_file: str, voice_text: str, voice_type: str = "") -> Tuple[str, Optional[str]]:
        return upload_character_sprite_voice(self._target(), character_name, sprite_index, voice_file, voice_text, voice_type, voice_dir=VOICE_DIR)

    def get_sprite_voice(self, character_name: str, sprite_index: int) -> Tuple[Optional[str], str]:
        return get_character_sprite_voice(self._target(), character_name, sprite_index)

    def save_sprite_voice_text(self, character_name: str, sprite_index: int, voice_text: str) -> str:
        return save_character_sprite_voice_text(self._target(), character_name, sprite_index, voice_text)

    def save_sprite_voice_type(self, character_name: str, sprite_index: int, voice_type: str) -> str:
        return save_character_sprite_voice_type(self._target(), character_name, sprite_index, voice_type)

    def delete_sprite_voice(self, character_name: str, sprite_index: int) -> str:
        return delete_character_sprite_voice(self._target(), character_name, sprite_index)

    def get_character_sprites(self, character_name: str) -> Tuple[List[str], str, List[Any]]:
        character = self._config_manager.get_character_by_name(character_name) if character_name else None
        if not character:
            return [], "", []
        paths = [s.path if isinstance(s, Sprite) else s.get("path", "") for s in (character.sprites or []) if s]
        return paths, character.emotion_tags or "", []

    def save_sprite_scale(self, name: str, scale: float) -> Any:
        if not name:
            return "名称不能为空！", [c.name for c in self._get_characters()]
        try:
            save_character_sprite_scale_op(self._target(), name, scale)
            return "保存立绘缩放倍率成功"
        except CharacterProfileError as exc:
            return str(exc)

    def load_characters_from_file(self) -> Tuple[str, List[List[str]]]:
        try:
            self._config_manager.reload()
            return "人物设定已加载！", [[c.name, c.color, c.prompt_lang or ""] for c in self._get_characters()]
        except Exception as exc:
            return f"加载失败: {exc}", [[c.name, c.color, c.prompt_lang or ""] for c in self._get_characters()]

    @staticmethod
    def _rename_relation_graph_owner(graph: RelationGraph, old_name: str, new_name: str) -> RelationGraph:
        return rename_relation_graph_owner(graph, old_name, new_name)

    @staticmethod
    def parse_relation_graph(data: Optional[Union[RelationGraph, Mapping[str, Any]]] = None) -> RelationGraph:
        return parse_relation_graph(data)

    def save_sprite_groups(self, name: str, **kwargs: Any) -> Character:
        return save_character_sprite_groups(self._target(), name, **kwargs)

    def update_relation_graph(self, char_name: str, mutate: Callable[[dict[str, Any]], Any]) -> RelationGraph:
        return update_character_relation_graph(self._target(), char_name, mutate)

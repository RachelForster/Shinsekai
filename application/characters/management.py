"""Character configuration-and-resource use cases."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from threading import RLock
from urllib.parse import urlparse

from application.media.resource_paths import MediaResourcePaths
from application.runtime.state import _jsonify

logger = logging.getLogger(__name__)


class CharacterOperation(str, Enum):
    IMPORT_MODEL = "import-model"
    IMPORT_MODEL_STATES = "import-model-states"
    SAVE_MODEL_STATE = "save-model-state"
    SAVE = "save"
    BIND_VOICE = "bind-voice"
    DELETE = "delete"
    UPLOAD_SPRITES = "upload-sprites"
    DELETE_SPRITE = "delete-sprite"
    DELETE_ALL_SPRITES = "delete-all-sprites"
    UPLOAD_SPRITE_VOICE = "upload-sprite-voice"
    SAVE_SPRITE_VOICE_TEXT = "save-sprite-voice-text"
    SAVE_SPRITE_VOICE_TYPE = "save-sprite-voice-type"
    DELETE_SPRITE_VOICE = "delete-sprite-voice"
    SAVE_SPRITE_GROUPS = "save-sprite-groups"
    AUTO_GROUP_SPRITES = "auto-group-sprites"
    IMPORT = "import"
    EXPORT = "export"


@dataclass(frozen=True)
class CharacterRequest:
    operation: CharacterOperation
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CharacterExportResult:
    """Transport-neutral reference to an exported character package."""

    path: str


def parse_character_request(
    operation: CharacterOperation,
    payload: dict[str, Any],
) -> CharacterRequest:
    if not isinstance(payload, dict):
        raise ValueError("character payload must be an object")
    return CharacterRequest(operation=operation, payload=dict(payload))


def validate_character_payload(body: dict[str, Any], *, allow_remote_voice_paths: bool = False) -> None:
    from config.schema import SELF_PERSONA_SPRITE_PREFIX, is_self_persona_name
    from sdk.ui.validators import (
        ascii_only,
        audio_duration_between,
        check_all,
        file_exists,
        no_quotes,
        not_empty,
    )

    sprite_prefix = str(body.get("sprite_prefix") or "").strip()
    if is_self_persona_name(body.get("name")) and not sprite_prefix:
        sprite_prefix = SELF_PERSONA_SPRITE_PREFIX
    gpt_model_path = str(body.get("gpt_model_path") or "").strip()
    sovits_model_path = str(body.get("sovits_model_path") or "").strip()
    refer_audio_path = str(body.get("refer_audio_path") or "").strip()

    def optional_suffix(value: str, suffix: str, label: str) -> tuple[bool, str]:
        if not value or value.lower().endswith(suffix):
            return True, ""
        return False, f"{label}: 文件后缀应为 {suffix}"

    checks = [
        not_empty(sprite_prefix, "立绘目录"),
        ascii_only(sprite_prefix, "立绘目录"),
        no_quotes(gpt_model_path, "GPT 模型路径"),
        optional_suffix(gpt_model_path, ".ckpt", "GPT 模型路径"),
        no_quotes(sovits_model_path, "SoVITS 模型路径"),
        optional_suffix(sovits_model_path, ".pth", "SoVITS 模型路径"),
        no_quotes(refer_audio_path, "参考音频"),
    ]
    if not allow_remote_voice_paths:
        checks.extend(
            [
                file_exists(gpt_model_path, "GPT 模型路径"),
                file_exists(sovits_model_path, "SoVITS 模型路径"),
                file_exists(refer_audio_path, "参考音频"),
                audio_duration_between(refer_audio_path, 3.0, 10.0, "参考音频"),
            ]
        )
    ok, errors = check_all(*checks)
    if not ok:
        raise ValueError("\n".join(errors))


class CharacterUseCase:
    """Single application entry point for character resource mutations."""
    _mutation_lock = RLock()

    def __init__(self, state: Any, *, file_access_roots: Iterable[Path] = ()):
        self._state = state
        project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
        self._resource_paths = MediaResourcePaths(
            project_root,
            file_access_roots=file_access_roots,
        )

    def execute(self, request: CharacterRequest) -> Any:
        from application.characters.model_assets import import_model, import_model_states, save_model_state
        handlers = {
            CharacterOperation.IMPORT_MODEL: lambda body: import_model(self, body),
            CharacterOperation.IMPORT_MODEL_STATES: lambda body: import_model_states(self, body),
            CharacterOperation.SAVE_MODEL_STATE: lambda body: save_model_state(self, body),
            CharacterOperation.SAVE: self._save,
            CharacterOperation.BIND_VOICE: self._bind_voice,
            CharacterOperation.DELETE: self._delete,
            CharacterOperation.UPLOAD_SPRITES: self._upload_sprites,
            CharacterOperation.DELETE_SPRITE: self._delete_sprite,
            CharacterOperation.DELETE_ALL_SPRITES: self._delete_all_sprites,
            CharacterOperation.UPLOAD_SPRITE_VOICE: self._upload_sprite_voice,
            CharacterOperation.SAVE_SPRITE_VOICE_TEXT: self._save_sprite_voice_text,
            CharacterOperation.SAVE_SPRITE_VOICE_TYPE: self._save_sprite_voice_type,
            CharacterOperation.DELETE_SPRITE_VOICE: self._delete_sprite_voice,
            CharacterOperation.SAVE_SPRITE_GROUPS: self._save_sprite_groups,
            CharacterOperation.AUTO_GROUP_SPRITES: self._auto_group_sprites,
            CharacterOperation.IMPORT: self._import_packages,
            CharacterOperation.EXPORT: self._export_package,
        }
        # Import prepares outside the lock, then checks the original config at commit.
        if request.operation in (CharacterOperation.IMPORT_MODEL, CharacterOperation.IMPORT_MODEL_STATES):
            return handlers[request.operation](request.payload)
        with self._mutation_lock:
            return handlers[request.operation](request.payload)

    def _character(self, name: str) -> Any:
        character = self._state.config_manager.get_character_by_name(name)
        if character is None:
            raise KeyError(f"character not found: {name}")
        return character

    def _refresh_characters_catalog(self) -> None:
        refresh = getattr(self._state.config_manager, "refresh_characters", None)
        if callable(refresh):
            refresh()
        else:
            self._state.config_manager.reload()

    def _after_reload(self, name: str) -> dict[str, Any]:
        self._refresh_characters_catalog()
        return _jsonify(self._character(name))

    def _file(self, raw: Any, *, field: str) -> Path:
        return self._resource_paths.input_file(raw, field=field)

    def _files(self, raw_paths: Any) -> list[Any]:
        return [
            SimpleNamespace(name=str(path))
            for path in self._resource_paths.input_files(
                raw_paths,
                field="character file",
            )
        ]

    @staticmethod
    def _is_remote_url(url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return bool(host and host not in {"127.0.0.1", "localhost", "0.0.0.0", "::1"})

    def _uses_remote_gpt_sovits(self) -> bool:
        api_config = self._state.config_manager.config.api_config
        provider = str(getattr(api_config, "tts_provider", "") or "").strip().lower()
        return provider == "kaggle-gpt-sovits" or (
            provider == "gpt-sovits" and self._is_remote_url(str(getattr(api_config, "gpt_sovits_url", "") or ""))
        )

    @staticmethod
    def _normalize_voice_type(value: Any, *, allow_empty: bool = False) -> str:
        voice_type = str(value or "").strip().lower()
        if not voice_type and allow_empty:
            return ""
        if voice_type not in {"fallback", "preset", "reference"}:
            raise ValueError("voice type must be fallback, preset, or reference")
        return voice_type

    @staticmethod
    def _sprite_voice_path(sprite: Any) -> str:
        if hasattr(sprite, "voice_path"):
            return str(sprite.voice_path or "")
        if isinstance(sprite, dict):
            return str(sprite.get("voice_path") or "")
        return ""

    @staticmethod
    def _validate_reference_audio(voice_path: str) -> None:
        if not voice_path.lower().endswith(".wav"):
            raise ValueError("参考语音必须是 WAV 格式")
        from sdk.ui.validators import audio_duration_between

        ok, error = audio_duration_between(voice_path, 3.0, 10.0, "参考语音")
        if not ok:
            raise ValueError(error)

    @staticmethod
    def _validate_sprite_voice_duration(voice_path: str, voice_text: str) -> None:
        if not voice_text.strip():
            return
        from sdk.ui.validators import audio_duration_between

        ok, error = audio_duration_between(voice_path, 3.0, 10.0, "语音")
        if not ok:
            raise ValueError(error)

    def _save(self, payload: dict[str, Any]) -> dict[str, Any]:
        from config.schema import (
            Character,
            PortraitCrop,
            SELF_PERSONA_SPRITE_PREFIX,
            is_self_persona_name,
        )

        body = payload.get("character", payload)
        if not isinstance(body, dict):
            raise ValueError("character payload must be an object")
        original_name = str(payload.get("originalName") or body.get("name") or "").strip()
        target_name = str(body.get("name") or "").strip()
        if original_name and is_self_persona_name(original_name) and not is_self_persona_name(target_name):
            raise ValueError("内置「自设」人物不可重命名")
        if original_name and not is_self_persona_name(original_name) and is_self_persona_name(target_name):
            raise ValueError("不能将其他角色重命名为「自设」")
        if is_self_persona_name(target_name) and not str(body.get("sprite_prefix") or "").strip():
            body = {**body, "sprite_prefix": SELF_PERSONA_SPRITE_PREFIX}
        if is_self_persona_name(target_name) and "display_name" in body:
            from core.chat_history.text import sanitize_user_display_name

            raw_name = str(body["display_name"] or "").strip()
            display_name = sanitize_user_display_name(raw_name)
            if raw_name and not display_name:
                raise ValueError("自设显示名无效，请使用 24 个字符以内的名称")
            body = {**body, "display_name": display_name}
        validate_character_payload(body, allow_remote_voice_paths=self._uses_remote_gpt_sovits())
        character = Character.model_validate(body)
        saved_name = character.name.strip()
        message, _names = self._state.character_manager.add_character(
            saved_name,
            str(character.color or "").strip() or "#d07d7d",
            character.sprite_prefix.strip() or "temp",
            str(character.gpt_model_path or "").strip(),
            str(character.sovits_model_path or "").strip(),
            str(character.refer_audio_path or "").strip(),
            str(character.prompt_text or "").strip(),
            str(character.prompt_lang or "").strip(),
            str(character.character_setting or "").strip(),
            speech_speed=character.speech_speed,
            speech_volume=character.speech_volume,
            pronunciation_map=character.pronunciation_map,
            edit_as_name=original_name,
            emotion_tags=str(character.emotion_tags or ""),
            character_brief=str(character.character_brief or "").strip(),
            portrait_crop=character.portrait_crop if "portrait_crop" in body else None,
            portrait_sprite_index=(
                character.portrait_sprite_index if "portrait_sprite_index" in body else None
            ),
            sprite_portrait_crops={
                index: (item.get("portrait_crop") and PortraitCrop.model_validate(item["portrait_crop"]))
                for index, item in enumerate(body.get("sprites", []))
                if isinstance(item, dict) and "portrait_crop" in item
            },
            sprite_group_map={
                index: item.get("group")
                for index, item in enumerate(body.get("sprites", []))
                if isinstance(item, dict) and "group" in item
            } or None,
            sprite_groups=character.sprite_groups if "sprite_groups" in body else None,
            default_sprite_group=character.default_sprite_group if "default_sprite_group" in body else None,
            fallback_to_default_group=(
                character.fallback_to_default_group if "fallback_to_default_group" in body else None
            ),
            # Preserve stored banks when older clients omit the new fields.
            avatar_type=character.avatar_type if "avatar_type" in body else None,
            avatars=character.avatars if "avatars" in body else None,
            relation_graph=character.relation_graph if "relation_graph" in body else None,
            **(
                {"display_name": character.display_name}
                if is_self_persona_name(saved_name) and "display_name" in body
                else {}
            ),
        )
        if (
            message.startswith("名称不能为空")
            or "已与其他角色重复" in message
            or "不可重命名" in message
            or "不能将其他角色重命名" in message
            or "占用" in message
            or message.startswith("保存失败")
        ):
            raise RuntimeError(message)
        self._refresh_characters_catalog()
        if original_name and original_name != saved_name:
            from application.chat.templates import _rename_template_session_character
            from application.chat.conversation_library import update_conversation_character

            # When unified AppStores is active, character_knowledge_bindings references immutable
            # character.id with ON DELETE CASCADE, so renames require zero binding cascade SQL.
            if getattr(self._state, "stores", None) is None:
                from application.knowledge.manage_knowledge import rename_character_bindings

                try:
                    rename_character_bindings(original_name, saved_name)
                except sqlite3.Error:
                    logger.exception(
                        "Character rename succeeded but knowledge bindings could not be migrated: %s -> %s",
                        original_name, saved_name,
                    )
            try:
                _rename_template_session_character(self._state, original_name, saved_name)
            except OSError:
                pass
            update_conversation_character(self._state, original_name, saved_name)
        saved = self._state.config_manager.get_character_by_name(saved_name)
        return _jsonify(saved or character)

    def _bind_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Atomically reload and update only voice-binding fields under ``_mutation_lock``."""
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("character name is required")
        self._refresh_characters_catalog()
        latest = self._character(name)
        merged = dict(_jsonify(latest))
        merged.update(
            {
                "gpt_model_path": str(payload.get("gpt_model_path") or "").strip(),
                "sovits_model_path": str(payload.get("sovits_model_path") or "").strip(),
                "refer_audio_path": str(payload.get("refer_audio_path") or "").strip(),
                "prompt_text": str(payload.get("prompt_text") or "").strip(),
                "prompt_lang": str(payload.get("prompt_lang") or "").strip(),
            }
        )
        return self._save({"originalName": name, "character": merged})

    def _delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        from application.chat.conversation_library import update_conversation_character
        from config.schema import is_self_persona_name

        name = str(payload.get("name") or "").strip()
        if is_self_persona_name(name):
            raise ValueError("内置「自设」人物不可删除")
        existing = self._state.config_manager.get_character_by_name(name)
        if existing is not None and getattr(existing, "undeletable", False):
            raise ValueError(f"内置人物「{existing.name}」不可删除")
        existed = existing is not None
        message, names = self._state.character_manager.delete_character(name)
        if existed and self._state.config_manager.get_character_by_name(name) is None:
            if getattr(self._state, "stores", None) is None:
                from application.knowledge.manage_knowledge import clear_character_bindings

                try:
                    clear_character_bindings(name)
                except sqlite3.Error:
                    logger.exception(
                        "Character deletion succeeded but knowledge bindings could not be cleared: %s", name,
                    )
            update_conversation_character(self._state, name)
        return {"message": message, "names": names}

    def _upload_sprites(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        group = payload.get("group")
        upload_kwargs: dict[str, Any] = {}
        if group is not None and str(group).strip():
            upload_kwargs["group"] = str(group).strip()
        message, _paths, _tags = self._state.character_manager.upload_sprites(
            name,
            self._files(payload.get("paths") or []),
            str(payload.get("emotionTags") or ""),
            **upload_kwargs,
        )
        if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _save_sprite_groups(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("character name is required")
        raw_assignments = payload.get("assignments")
        assignments: dict[int, str | None] | None = None
        if isinstance(raw_assignments, dict):
            assignments = {
                int(k): (None if v is None else str(v))
                for k, v in raw_assignments.items()
            }
        raw_groups = payload.get("spriteGroups")
        sprite_groups = [str(g) for g in raw_groups] if isinstance(raw_groups, list) else None
        self._state.character_manager.save_sprite_groups(
            name,
            sprite_groups=sprite_groups,
            default_sprite_group=(
                str(payload["defaultSpriteGroup"])
                if "defaultSpriteGroup" in payload and payload["defaultSpriteGroup"] is not None
                else None
            ),
            fallback_to_default_group=(
                bool(payload["fallbackToDefaultGroup"])
                if "fallbackToDefaultGroup" in payload and payload["fallbackToDefaultGroup"] is not None
                else None
            ),
            assignments=assignments,
            rename_from=(
                str(payload["renameFrom"])
                if payload.get("renameFrom") is not None
                else None
            ),
            rename_to=(
                str(payload["renameTo"])
                if payload.get("renameTo") is not None
                else None
            ),
            delete_group=(
                str(payload["deleteGroup"])
                if payload.get("deleteGroup") is not None
                else None
            ),
            avatar_type=(
                str(payload["avatarType"])
                if payload.get("avatarType") is not None
                else None
            ),
        )
        return self._after_reload(name)

    def _auto_group_sprites(self, payload: dict[str, Any]) -> dict[str, Any]:
        from application.characters.sprite.auto_group_sprites import analyze_character_sprite_groups

        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("character name is required")
        character = self._character(name)
        avatar_type = (
            str(payload["avatarType"]).strip()
            if payload.get("avatarType") is not None
            else None
        )
        overwrite_existing = bool(payload.get("overwriteExisting", False))
        apply_now = bool(payload.get("apply", False))
        analysis = analyze_character_sprite_groups(
            character,
            avatar_type=avatar_type,
            overwrite_existing=overwrite_existing,
        )
        updated_char = None
        if apply_now and analysis.get("assignments"):
            assignments = {
                int(k): str(v)
                for k, v in dict(analysis["assignments"]).items()
            }
            self._state.character_manager.save_sprite_groups(
                name,
                sprite_groups=list(analysis.get("spriteGroups") or []),
                assignments=assignments,
                avatar_type=avatar_type,
            )
            updated_char = self._after_reload(name)
        return {
            **analysis,
            "applied": apply_now,
            "character": updated_char,
        }

    def _delete_sprite(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.character_manager.delete_single_sprite(
            name,
            int(payload.get("spriteIndex") or 0),
        )
        if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _delete_all_sprites(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.character_manager.delete_all_sprites(name)
        if message.startswith("找不到") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _upload_sprite_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        sprite_index = int(payload.get("spriteIndex") or 0)
        voice_text = str(payload.get("voiceText") or "").strip()
        character = self._character(name)
        voice_type = self._normalize_voice_type(payload.get("voiceType"), allow_empty=True)
        if not voice_type:
            has_model = bool(
                str(getattr(character, "gpt_model_path", "") or "").strip()
                and str(getattr(character, "sovits_model_path", "") or "").strip()
            )
            voice_type = "reference" if has_model else "fallback"
        raw_voice_path = str(payload.get("voicePath") or "").strip()
        if not raw_voice_path:
            raise ValueError("voice path is required")
        voice_path = self._file(raw_voice_path, field="voice path")
        if voice_type == "reference":
            self._validate_reference_audio(str(voice_path))
        message, _path = self._state.character_manager.upload_voice(
            name,
            sprite_index,
            str(voice_path),
            voice_text,
            voice_type,
        )
        if (
            message.startswith("找不到")
            or message.startswith("立绘不存在")
            or message.startswith("请选择")
            or message.startswith("请先")
        ):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _save_sprite_voice_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        sprite_index = int(payload.get("spriteIndex") or 0)
        voice_text = str(payload.get("voiceText") or "").strip()
        character = self._character(name)
        sprites = getattr(character, "sprites", []) or []
        if 0 <= sprite_index < len(sprites):
            sprite = sprites[sprite_index]
            voice_type = getattr(sprite, "voice_type", None)
            if isinstance(sprite, dict):
                voice_type = sprite.get("voice_type")
            if voice_type == "reference":
                voice_path = self._sprite_voice_path(sprite)
                if voice_path and Path(voice_path).is_file():
                    self._validate_sprite_voice_duration(voice_path, voice_text)
        message = self._state.character_manager.save_sprite_voice_text(name, sprite_index, voice_text)
        if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _save_sprite_voice_type(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        sprite_index = int(payload.get("spriteIndex") or 0)
        voice_type = self._normalize_voice_type(payload.get("voiceType"))
        character = self._character(name)
        sprites = getattr(character, "sprites", []) or []
        if voice_type == "reference" and 0 <= sprite_index < len(sprites):
            voice_path = self._sprite_voice_path(sprites[sprite_index])
            if voice_path:
                if not Path(voice_path).is_file():
                    raise ValueError("reference audio file does not exist")
                self._validate_reference_audio(voice_path)
        message = self._state.character_manager.save_sprite_voice_type(name, sprite_index, voice_type)
        if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _delete_sprite_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message = self._state.character_manager.delete_sprite_voice(
            name,
            int(payload.get("spriteIndex") or 0),
        )
        if message.startswith("找不到") or message.startswith("立绘不存在") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _import_packages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        files = self._files(payload.get("paths") or [])
        from core.packaging.character_package import stage_character_package_import
        from core.packaging.zip_io import rollback_staged_assets
        from tools import file_util

        stores = getattr(self._state, "stores", None)
        project_root = self._resource_paths.project_root
        default_data = Path("./data")
        sprite_dir = (
            Path(file_util.SPRITE_DIR)
            if file_util.SPRITE_DIR != default_data / "sprite"
            else (stores.layout.media_dir("sprite") if stores is not None else project_root / "data" / "sprite")
        )
        speech_dir = (
            Path(file_util.SPEECH_DIR)
            if file_util.SPEECH_DIR != default_data / "speech"
            else (stores.layout.media_dir("speech") if stores is not None else project_root / "data" / "speech")
        )
        model_dir = (
            Path(file_util.MODEL_DIR)
            if file_util.MODEL_DIR != default_data / "models"
            else (stores.layout.media_dir("models") if stores is not None else project_root / "data" / "models")
        )

        existing_source = (
            stores.characters.list_all()
            if stores is not None
            else (getattr(getattr(self._state.config_manager, "config", None), "characters", None) or ())
        )
        existing_names = {c.name for c in existing_source if getattr(c, "name", "")}
        existing_prefixes = {c.sprite_prefix for c in existing_source if getattr(c, "sprite_prefix", "")}

        imported = []
        created_dirs: list[Path] = []
        try:
            for item in files:
                staged = stage_character_package_import(
                    item.name,
                    existing_names=existing_names,
                    existing_prefixes=existing_prefixes,
                    sprite_dir=sprite_dir,
                    speech_dir=speech_dir,
                    model_dir=model_dir,
                    cwd_base=Path.cwd(),
                )
                created_dirs.extend(staged.created_dirs)
                imported.extend(staged.characters)
                for char in staged.characters:
                    existing_names.add(char.name)
                    existing_prefixes.add(char.sprite_prefix)

            if stores is not None:
                with stores.main_db.atomic():
                    for char in imported:
                        stores.characters.put(char.id, char)
                self._refresh_characters_catalog()
            else:
                chars = getattr(self._state.config_manager.config, "characters", None)
                if isinstance(chars, list):
                    chars.extend(imported)
                self._state.config_manager.save_characters_config()
                self._refresh_characters_catalog()
            return [_jsonify(char) for char in imported]
        except BaseException:
            rollback_staged_assets(created_dirs)
            raise

    def _export_package(self, payload: dict[str, Any]) -> CharacterExportResult:
        name = str(payload.get("name") or "")
        character = self._character(name)
        from tools.file_util import export_character

        output, relative = self._resource_paths.export_target(name, ".char")
        export_character([character], output.as_posix(), open_folder=False)
        return CharacterExportResult(path=relative)

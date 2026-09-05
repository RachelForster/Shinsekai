"""Character configuration-and-resource use cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from urllib.parse import urlparse

from application.media.resource_paths import MediaResourcePaths
from application.runtime.state import _jsonify


class CharacterOperation(str, Enum):
    SAVE = "save"
    DELETE = "delete"
    UPLOAD_SPRITES = "upload-sprites"
    DELETE_SPRITE = "delete-sprite"
    DELETE_ALL_SPRITES = "delete-all-sprites"
    UPLOAD_SPRITE_VOICE = "upload-sprite-voice"
    SAVE_SPRITE_VOICE_TEXT = "save-sprite-voice-text"
    SAVE_SPRITE_VOICE_TYPE = "save-sprite-voice-type"
    DELETE_SPRITE_VOICE = "delete-sprite-voice"
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
    from sdk.ui.validators import (
        ascii_only,
        audio_duration_between,
        check_all,
        file_exists,
        no_quotes,
        not_empty,
    )

    sprite_prefix = str(body.get("sprite_prefix") or "").strip()
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

    def __init__(self, state: Any, *, file_access_roots: Iterable[Path] = ()):
        self._state = state
        project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
        self._resource_paths = MediaResourcePaths(
            project_root,
            file_access_roots=file_access_roots,
        )

    def execute(self, request: CharacterRequest) -> Any:
        handlers = {
            CharacterOperation.SAVE: self._save,
            CharacterOperation.DELETE: self._delete,
            CharacterOperation.UPLOAD_SPRITES: self._upload_sprites,
            CharacterOperation.DELETE_SPRITE: self._delete_sprite,
            CharacterOperation.DELETE_ALL_SPRITES: self._delete_all_sprites,
            CharacterOperation.UPLOAD_SPRITE_VOICE: self._upload_sprite_voice,
            CharacterOperation.SAVE_SPRITE_VOICE_TEXT: self._save_sprite_voice_text,
            CharacterOperation.SAVE_SPRITE_VOICE_TYPE: self._save_sprite_voice_type,
            CharacterOperation.DELETE_SPRITE_VOICE: self._delete_sprite_voice,
            CharacterOperation.IMPORT: self._import_packages,
            CharacterOperation.EXPORT: self._export_package,
        }
        return handlers[request.operation](request.payload)

    def _character(self, name: str) -> Any:
        character = self._state.config_manager.get_character_by_name(name)
        if character is None:
            raise KeyError(f"character not found: {name}")
        return character

    def _after_reload(self, name: str) -> dict[str, Any]:
        self._state.config_manager.reload()
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
        from config.schema import Character

        body = payload.get("character", payload)
        if not isinstance(body, dict):
            raise ValueError("character payload must be an object")
        original_name = str(payload.get("originalName") or body.get("name") or "").strip()
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
        )
        if message.startswith("名称不能为空") or "已与其他角色重复" in message or message.startswith("保存失败"):
            raise RuntimeError(message)
        self._state.config_manager.reload()
        if original_name and original_name != saved_name:
            from application.chat.templates import _rename_template_session_character

            try:
                _rename_template_session_character(self._state, original_name, saved_name)
            except OSError:
                pass
        saved = self._state.config_manager.get_character_by_name(saved_name)
        return _jsonify(saved or character)

    def _delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        message, names = self._state.character_manager.delete_character(str(payload.get("name") or "").strip())
        return {"message": message, "names": names}

    def _upload_sprites(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.character_manager.upload_sprites(
            name,
            self._files(payload.get("paths") or []),
            str(payload.get("emotionTags") or ""),
        )
        if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

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
        from tools.file_util import import_character

        imported = []
        for item in files:
            imported.extend(import_character(item.name))
        self._state.config_manager.reload()
        return [dict(item.__dict__) for item in imported]

    def _export_package(self, payload: dict[str, Any]) -> CharacterExportResult:
        name = str(payload.get("name") or "")
        character = self._character(name)
        from config.character_config import CharacterConfig
        from tools.file_util import export_character

        data = character.model_dump(mode="json") if hasattr(character, "model_dump") else dict(character)
        config = CharacterConfig.parse_dic(data)
        output, relative = self._resource_paths.export_target(name, ".char")
        export_character([config], output.as_posix(), open_folder=False)
        return CharacterExportResult(path=relative)

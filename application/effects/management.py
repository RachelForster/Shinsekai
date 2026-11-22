"""Application use case for effect configuration and managed media resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import contextlib
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path, PureWindowsPath
import shutil
from typing import Any, TypeAlias

from config.schema import Effect
from core.media.asset_tags import numbered_tags, tag_content as _tag_text, tag_contents
from core.packaging.effect_package import (
    export_effect_package,
    stage_effect_package_import,
    validate_effect_storage_name,
)
from core.packaging.zip_io import rollback_staged_assets
from core.storage.stores import EffectCatalogPort
from sdk.path_utils import (
    safe_child_path,
    safe_existing_file_path,
    safe_filename,
    safe_project_path,
)


class EffectOperation(str, Enum):
    SAVE = "save"
    DELETE = "delete"
    UPLOAD_AUDIO = "upload-audio"
    DELETE_AUDIO = "delete-audio"
    DELETE_ALL_AUDIO = "delete-all-audio"
    SAVE_AUDIO_TAGS = "save-audio-tags"
    UPLOAD_IMAGES = "upload-images"
    DELETE_IMAGE = "delete-image"
    SAVE_IMAGE_TAGS = "save-image-tags"
    UPLOAD_IMAGE_AUDIO = "upload-image-audio"
    UPLOAD_AMBIENT = "upload-ambient"
    DELETE_AMBIENT = "delete-ambient"
    SAVE_AMBIENT_TAGS = "save-ambient-tags"
    SAVE_AMBIENT_LAYERS = "save-ambient-layers"
    UPLOAD_AMBIENT_AUDIO = "upload-ambient-audio"
    IMPORT = "import"
    EXPORT = "export"


@dataclass(frozen=True, slots=True)
class EffectRequest:
    operation: EffectOperation
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EffectExportResult:
    path: str


EffectUseCaseResult: TypeAlias = Effect | list[Effect] | dict[str, Any] | EffectExportResult

_AMBIENT_MEDIA_SUFFIXES = frozenset(
    {
        ".apng",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4v",
        ".mov",
        ".mp4",
        ".png",
        ".webm",
        ".webp",
    }
)


def _file_digest(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


class EffectUseCase:
    """Own effect config/resource updates behind one application entry point."""

    def __init__(
        self,
        config_manager: Any = None,
        *,
        effects: EffectCatalogPort | None = None,
        local_file_access_roots: Sequence[str | os.PathLike[str]] = (),
        project_root: str | os.PathLike[str] | None = None,
    ) -> None:
        if config_manager is None and effects is None:
            raise ValueError("either config_manager or effects must be provided")
        self.config_manager = config_manager
        self.effects = effects
        self.project_root = Path(project_root or Path.cwd()).resolve(strict=False)
        self.local_file_access_roots = tuple(
            Path(root).resolve(strict=False) for root in local_file_access_roots
        )

    def execute(self, request: EffectRequest) -> EffectUseCaseResult:
        handlers = {
            EffectOperation.SAVE: self._save,
            EffectOperation.DELETE: self._delete,
            EffectOperation.UPLOAD_AUDIO: self._upload_audio,
            EffectOperation.DELETE_AUDIO: self._delete_audio,
            EffectOperation.DELETE_ALL_AUDIO: self._delete_all_audio,
            EffectOperation.SAVE_AUDIO_TAGS: self._save_audio_tags,
            EffectOperation.UPLOAD_IMAGES: self._upload_images,
            EffectOperation.DELETE_IMAGE: self._delete_image,
            EffectOperation.SAVE_IMAGE_TAGS: self._save_image_tags,
            EffectOperation.UPLOAD_IMAGE_AUDIO: self._upload_image_audio,
            EffectOperation.UPLOAD_AMBIENT: self._upload_ambient,
            EffectOperation.DELETE_AMBIENT: self._delete_ambient,
            EffectOperation.SAVE_AMBIENT_TAGS: self._save_ambient_tags,
            EffectOperation.SAVE_AMBIENT_LAYERS: self._save_ambient_layers,
            EffectOperation.UPLOAD_AMBIENT_AUDIO: self._upload_ambient_audio,
            EffectOperation.IMPORT: self._import,
            EffectOperation.EXPORT: self._export,
        }
        try:
            handler = handlers[request.operation]
        except KeyError as error:
            raise ValueError(f"unsupported effect operation: {request.operation}") from error
        return handler(dict(request.payload))

    @property
    def effect_root(self) -> Path:
        return safe_project_path("data/effects", root=self.project_root)

    def _effect_dir(self, name: str) -> Path:
        safe_name = validate_effect_storage_name(name)
        candidate = safe_child_path(self.effect_root, safe_name)
        if candidate == self.effect_root:
            raise ValueError("effect directory escapes managed storage")
        return candidate

    def _effect_by_name(self, name: str) -> Any:
        if self.effects is not None:
            effect = self.effects.get_by_name(name)
        else:
            effect = self.config_manager.get_effect_by_name(name)
        if effect is None:
            raise KeyError(f"effect not found: {name}")
        return effect

    def _sync_config_manager(self) -> None:
        if self.config_manager is None:
            return
        refresh = getattr(self.config_manager, "refresh_effects", None)
        if callable(refresh):
            refresh()
        else:
            self.config_manager.reload()

    def _effect_after_reload(self, name: str) -> Any:
        self._sync_config_manager()
        return self._effect_by_name(name)

    def _save_updated_effect(self, effect: Effect, **updates: Any) -> Effect:
        if self.effects is not None:
            updated = effect.model_copy(update=updates) if hasattr(effect, "model_copy") else effect
            if not hasattr(effect, "model_copy"):
                for field, value in updates.items():
                    setattr(effect, field, value)
            self.effects.put(updated.id, updated)
            self._sync_config_manager()
            return self._effect_by_name(updated.name)
        for field, value in updates.items():
            setattr(effect, field, value)
        self.config_manager.save_effect_config()
        return self._effect_after_reload(effect.name)

    def _save(self, payload: dict[str, Any]) -> Effect:
        raw_body = payload.get("effect", payload)
        if not isinstance(raw_body, Mapping):
            raise ValueError("effect payload must be an object")
        body = dict(raw_body)
        name = validate_effect_storage_name(str(body.get("name") or "").strip())
        original_name = str(payload.get("originalName") or "").strip()
        if original_name:
            validate_effect_storage_name(original_name)

        existing_effects = (
            list(self.effects.list_all())
            if self.effects is not None
            else self.config_manager.config.effect_list
        )
        if original_name:
            original = self._effect_by_name(original_name)
            body["id"] = original.id
            remaining = [
                effect
                for effect in existing_effects
                if effect.name.lower() != original_name.lower()
            ]
            existing_names = {effect.name.lower() for effect in remaining}
            base_name = name
            counter = 1
            while name.lower() in existing_names:
                name = f"{base_name}_{counter}"
                counter += 1
            body["name"] = name
            updated = Effect.model_validate(body)
            old_dir = self._effect_dir(original.name)
            new_dir = self._effect_dir(updated.name)
            if old_dir.is_dir() and old_dir != new_dir:
                body["audio_list"] = self._renamed_asset_paths(
                    body.get("audio_list"), old_dir, new_dir
                )
                if "image_list" in body:
                    body["image_list"] = self._renamed_asset_paths(
                        body.get("image_list"), old_dir, new_dir
                    )
                if "image_audio_list" in body:
                    body["image_audio_list"] = self._renamed_asset_paths(
                        body.get("image_audio_list"), old_dir, new_dir
                    )
                if "ambient_list" in body:
                    body["ambient_list"] = self._renamed_asset_paths(
                        body.get("ambient_list"), old_dir, new_dir
                    )
                if "ambient_audio_list" in body:
                    body["ambient_audio_list"] = self._renamed_asset_paths(
                        body.get("ambient_audio_list"), old_dir, new_dir
                    )
                updated = Effect.model_validate(body)
                self._move_effect_dir(old_dir, new_dir)
            if self.effects is not None:
                self.effects.put(updated.id, updated)
                self._effect_dir(updated.name).mkdir(parents=True, exist_ok=True)
                self._sync_config_manager()
                return self._effect_by_name(updated.name)
            existing_effects[:] = [*remaining, updated]
        else:
            existing_match = next(
                (eff for eff in existing_effects if eff.name.lower() == name.lower()),
                None,
            )
            if existing_match is not None and "id" not in body:
                body["id"] = existing_match.id
            updated = Effect.model_validate(body)
            if self.effects is not None:
                self.effects.put(updated.id, updated)
                self._effect_dir(updated.name).mkdir(parents=True, exist_ok=True)
                self._sync_config_manager()
                return self._effect_by_name(updated.name)
            existing_effects[:] = [
                effect
                for effect in existing_effects
                if effect.name.lower() != updated.name.lower()
            ]
            existing_effects.append(updated)

        self.config_manager.save_effect_config()
        self._effect_dir(updated.name).mkdir(parents=True, exist_ok=True)
        return self._effect_after_reload(updated.name)

    def _delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = validate_effect_storage_name(str(payload.get("name") or ""))
        if self.effects is not None:
            match = self._effect_by_name(name)
            self.effects.delete(match.id)
            self._sync_config_manager()
        else:
            effect_list = self.config_manager.config.effect_list
            match = next(
                (effect for effect in effect_list if effect.name.lower() == name.lower()),
                None,
            )
            if match is None:
                raise KeyError(f"effect not found: {name}")
            effect_list.remove(match)
            self.config_manager.save_effect_config()
        effect_dir = self._effect_dir(match.name)
        if effect_dir.is_dir():
            shutil.rmtree(effect_dir, ignore_errors=True)
        return {}

    def _upload_audio(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        paths = payload.get("paths") or []
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes, bytearray)):
            raise ValueError("paths must be a list")
        effect = self._effect_by_name(name)
        effect_dir = self._effect_dir(name)
        effect_dir.mkdir(parents=True, exist_ok=True)
        audio_list = list(effect.audio_list or [])
        tags = tag_contents(
            str(payload.get("audioTags") or effect.audio_tags or ""),
            len(audio_list),
            preserve_blank_lines=True,
        )
        known_digests = self._managed_asset_digests(name, audio_list)

        for raw_path in paths:
            try:
                source = safe_existing_file_path(
                    str(raw_path),
                    roots=self.local_file_access_roots,
                    field="effect asset path",
                )
            except (OSError, ValueError, FileNotFoundError):
                continue
            digest = _file_digest(source)
            if digest and digest in known_digests:
                continue
            destination = self._available_destination(effect_dir, source.name)
            shutil.copy2(source, destination)
            if digest:
                known_digests.add(digest)
            destination_text = destination.as_posix()
            if destination_text not in audio_list:
                audio_list.append(destination_text)
                tags.append("")

        return self._save_updated_effect(
            effect,
            audio_list=audio_list,
            audio_tags=numbered_tags("特效", tags),
        )

    def _delete_audio(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        index = int(payload.get("index") or 0)
        effect = self._effect_by_name(name)
        audio_list = list(effect.audio_list or [])
        if index < 0 or index >= len(audio_list):
            raise IndexError(f"audio index out of range: {index}")

        removed_path = audio_list.pop(index)
        self._unlink_managed_file(name, removed_path)
        tag_lines = str(effect.audio_tags or "").splitlines()
        while tag_lines and not tag_lines[-1].strip():
            tag_lines.pop()
        if index < len(tag_lines):
            tag_lines.pop(index)
        return self._save_updated_effect(
            effect,
            audio_list=audio_list,
            audio_tags="".join(
                f"特效 {position + 1}：{_tag_text(line)}\n"
                for position, line in enumerate(tag_lines)
            ),
        )

    def _delete_all_audio(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        effect = self._effect_by_name(name)
        for path in effect.audio_list or ():
            self._unlink_managed_file(name, str(path))
        return self._save_updated_effect(effect, audio_list=[], audio_tags="")

    def _save_audio_tags(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        effect = self._effect_by_name(name)
        new_tags = str(payload.get("audioTags") or "")
        lines = new_tags.splitlines()
        missing = [
            str(index + 1)
            for index in range(len(effect.audio_list or ()))
            if index >= len(lines) or not _tag_text(lines[index])
        ]
        if missing:
            print(
                f"[Effect] 警告：特效方案 '{name}' 的第 {', '.join(missing)} 个音频"
                "未输入提示词，将无法通过关键词触发。"
            )
        return self._save_updated_effect(effect, audio_tags=new_tags)

    def _upload_images(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        paths = payload.get("paths") or []
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes, bytearray)):
            raise ValueError("paths must be a list")
        effect = self._effect_by_name(name)
        effect_dir = self._effect_dir(name)
        effect_dir.mkdir(parents=True, exist_ok=True)
        image_list = list(effect.image_list or [])
        image_audio_list = list(effect.image_audio_list or [])
        image_audio_list.extend("" for _ in range(len(image_list) - len(image_audio_list)))
        tags = tag_contents(
            str(payload.get("imageTags") or effect.image_tags or ""),
            len(image_list),
            preserve_blank_lines=True,
        )
        known_digests = self._managed_asset_digests(name, image_list)

        for raw_path in paths:
            try:
                source = safe_existing_file_path(
                    str(raw_path),
                    roots=self.local_file_access_roots,
                    field="effect image path",
                )
            except (OSError, ValueError, FileNotFoundError):
                continue
            if source.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            digest = _file_digest(source)
            if digest and digest in known_digests:
                continue
            destination = self._available_destination(effect_dir, source.name)
            shutil.copy2(source, destination)
            if digest:
                known_digests.add(digest)
            image_list.append(destination.as_posix())
            image_audio_list.append("")
            tags.append("")

        return self._save_updated_effect(
            effect,
            image_list=image_list,
            image_audio_list=image_audio_list,
            image_tags=numbered_tags("图片", tags),
        )

    def _delete_image(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        index = int(payload.get("index") or 0)
        effect = self._effect_by_name(name)
        image_list = list(effect.image_list or [])
        image_audio_list = list(effect.image_audio_list or [])
        if index < 0 or index >= len(image_list):
            raise IndexError(f"image index out of range: {index}")

        self._unlink_managed_file(name, image_list.pop(index))
        if index < len(image_audio_list):
            self._unlink_managed_file(name, image_audio_list.pop(index))
        tag_lines = str(effect.image_tags or "").splitlines()
        while tag_lines and not tag_lines[-1].strip():
            tag_lines.pop()
        if index < len(tag_lines):
            tag_lines.pop(index)
        return self._save_updated_effect(
            effect,
            image_list=image_list,
            image_audio_list=image_audio_list,
            image_tags="".join(
                f"图片 {position + 1}：{_tag_text(line)}\n"
                for position, line in enumerate(tag_lines)
            ),
        )

    def _save_image_tags(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        effect = self._effect_by_name(name)
        return self._save_updated_effect(effect, image_tags=str(payload.get("imageTags") or ""))

    def _upload_image_audio(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        index = int(payload.get("index") or 0)
        effect = self._effect_by_name(name)
        image_list = list(effect.image_list or [])
        if index < 0 or index >= len(image_list):
            raise IndexError(f"image index out of range: {index}")
        source = safe_existing_file_path(
            str(payload.get("path") or ""),
            roots=self.local_file_access_roots,
            field="effect image audio path",
        )
        if source.suffix.lower() not in {".flac", ".m4a", ".mp3", ".ogg", ".wav"}:
            raise ValueError("unsupported effect image audio format")

        effect_dir = self._effect_dir(name)
        effect_dir.mkdir(parents=True, exist_ok=True)
        destination = self._available_destination(effect_dir, source.name)
        shutil.copy2(source, destination)
        image_audio_list = list(effect.image_audio_list or [])
        image_audio_list.extend("" for _ in range(len(image_list) - len(image_audio_list)))
        self._unlink_managed_file(name, image_audio_list[index])
        image_audio_list[index] = destination.as_posix()
        return self._save_updated_effect(effect, image_audio_list=image_audio_list)

    def _upload_ambient(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        paths = payload.get("paths") or []
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes, bytearray)):
            raise ValueError("paths must be a list")
        effect = self._effect_by_name(name)
        effect_dir = self._effect_dir(name)
        effect_dir.mkdir(parents=True, exist_ok=True)
        ambient_list = list(effect.ambient_list or [])
        ambient_audio_list = list(effect.ambient_audio_list or [])
        ambient_layers = list(effect.ambient_layers or [])
        ambient_audio_list.extend("" for _ in range(len(ambient_list) - len(ambient_audio_list)))
        ambient_layers.extend("back" for _ in range(len(ambient_list) - len(ambient_layers)))
        tags = tag_contents(
            str(payload.get("ambientTags") or effect.ambient_tags or ""),
            len(ambient_list),
            preserve_blank_lines=True,
        )
        known_digests = self._managed_asset_digests(name, ambient_list)

        for raw_path in paths:
            try:
                source = safe_existing_file_path(
                    str(raw_path),
                    roots=self.local_file_access_roots,
                    field="effect ambient asset path",
                )
            except (OSError, ValueError, FileNotFoundError):
                continue
            if source.suffix.lower() not in _AMBIENT_MEDIA_SUFFIXES:
                continue
            digest = _file_digest(source)
            if digest and digest in known_digests:
                continue
            destination = self._available_destination(effect_dir, source.name)
            shutil.copy2(source, destination)
            if digest:
                known_digests.add(digest)
            ambient_list.append(destination.as_posix())
            ambient_audio_list.append("")
            ambient_layers.append("back")
            tags.append("")

        return self._save_updated_effect(
            effect,
            ambient_list=ambient_list,
            ambient_audio_list=ambient_audio_list,
            ambient_layers=ambient_layers,
            ambient_tags=numbered_tags("环境", tags),
        )

    def _delete_ambient(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        index = int(payload.get("index") or 0)
        effect = self._effect_by_name(name)
        ambient_list = list(effect.ambient_list or [])
        ambient_audio_list = list(effect.ambient_audio_list or [])
        ambient_layers = list(effect.ambient_layers or [])
        if index < 0 or index >= len(ambient_list):
            raise IndexError(f"ambient index out of range: {index}")

        self._unlink_managed_file(name, ambient_list.pop(index))
        if index < len(ambient_audio_list):
            self._unlink_managed_file(name, ambient_audio_list.pop(index))
        if index < len(ambient_layers):
            ambient_layers.pop(index)
        tag_lines = str(effect.ambient_tags or "").splitlines()
        while tag_lines and not tag_lines[-1].strip():
            tag_lines.pop()
        if index < len(tag_lines):
            tag_lines.pop(index)
        return self._save_updated_effect(
            effect,
            ambient_list=ambient_list,
            ambient_audio_list=ambient_audio_list,
            ambient_layers=ambient_layers,
            ambient_tags="".join(
                f"环境 {position + 1}：{_tag_text(line)}\n"
                for position, line in enumerate(tag_lines)
            ),
        )

    def _save_ambient_tags(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        effect = self._effect_by_name(name)
        return self._save_updated_effect(
            effect, ambient_tags=str(payload.get("ambientTags") or "")
        )

    def _save_ambient_layers(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        effect = self._effect_by_name(name)
        raw_layers = payload.get("layers") or []
        if not isinstance(raw_layers, Sequence) or isinstance(
            raw_layers, (str, bytes, bytearray)
        ):
            raise ValueError("layers must be a list")
        layers = [
            "front" if str(value or "").strip().lower() == "front" else "back"
            for value in raw_layers
        ]
        layers = layers[: len(effect.ambient_list or ())]
        layers.extend("back" for _ in range(len(effect.ambient_list or ()) - len(layers)))
        return self._save_updated_effect(effect, ambient_layers=layers)

    def _upload_ambient_audio(self, payload: dict[str, Any]) -> Effect:
        name = validate_effect_storage_name(str(payload.get("name") or "").strip())
        index = int(payload.get("index") or 0)
        effect = self._effect_by_name(name)
        ambient_list = list(effect.ambient_list or [])
        if index < 0 or index >= len(ambient_list):
            raise IndexError(f"ambient index out of range: {index}")
        source = safe_existing_file_path(
            str(payload.get("path") or ""),
            roots=self.local_file_access_roots,
            field="effect ambient audio path",
        )
        if source.suffix.lower() not in {".flac", ".m4a", ".mp3", ".ogg", ".wav"}:
            raise ValueError("unsupported effect ambient audio format")

        effect_dir = self._effect_dir(name)
        effect_dir.mkdir(parents=True, exist_ok=True)
        destination = self._available_destination(effect_dir, source.name)
        shutil.copy2(source, destination)
        ambient_audio_list = list(effect.ambient_audio_list or [])
        ambient_audio_list.extend("" for _ in range(len(ambient_list) - len(ambient_audio_list)))
        self._unlink_managed_file(name, ambient_audio_list[index])
        ambient_audio_list[index] = destination.as_posix()
        return self._save_updated_effect(
            effect, ambient_audio_list=ambient_audio_list
        )

    def _import(self, payload: dict[str, Any]) -> list[Effect]:
        paths = payload.get("paths") or []
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes, bytearray)):
            raise ValueError("paths must be a list")
        existing = (
            list(self.effects.list_all())
            if self.effects is not None
            else self.config_manager.config.effect_list
        )
        imported: list[Effect] = []
        created_dirs: list[Path] = []
        committed = False
        try:
            for raw_path in paths:
                archive = safe_existing_file_path(
                    str(raw_path),
                    roots=self.local_file_access_roots,
                    field="effect package path",
                )
                staged = stage_effect_package_import(
                    archive,
                    existing_effects=[*existing, *imported],
                    effect_root=self.effect_root,
                )
                created_dirs.extend(staged.created_dirs)
                imported.extend(staged.effects)
            if self.effects is not None:
                atomic = getattr(self.effects, "atomic", None)
                with atomic() if callable(atomic) else contextlib.nullcontext():
                    for effect in imported:
                        self._effect_dir(effect.name).mkdir(parents=True, exist_ok=True)
                        self.effects.put(effect.id, effect)
                committed = True
                self._sync_config_manager()
                return imported
            for effect in imported:
                if effect not in existing:
                    existing.append(effect)
                self._effect_dir(effect.name).mkdir(parents=True, exist_ok=True)
            self.config_manager.save_effect_config()
            committed = True
            self._sync_config_manager()
            return imported
        except BaseException:
            if not committed:
                rollback_staged_assets(created_dirs)
            raise

    def _export(self, payload: dict[str, Any]) -> EffectExportResult:
        name = validate_effect_storage_name(str(payload.get("name") or ""))
        effect = self._effect_by_name(name)
        output_root = safe_project_path("output", root=self.project_root)
        output_root.mkdir(parents=True, exist_ok=True)
        output = safe_child_path(output_root, safe_filename(f"{name}.ef"))
        export_effect_package(
            effect,
            output,
            effect_root=self.effect_root,
            project_root=self.project_root,
            local_file_access_roots=self.local_file_access_roots,
        )
        return EffectExportResult(output.relative_to(self.project_root).as_posix())

    def _managed_file(self, effect_name: str, raw_path: str) -> Path | None:
        if not raw_path:
            return None
        root = self._effect_dir(effect_name).resolve(strict=False)
        try:
            candidate = self._configured_path(raw_path)
            return safe_existing_file_path(
                candidate,
                roots=[root],
                field="effect asset path",
            )
        except (OSError, ValueError, FileNotFoundError):
            return None

    def _unlink_managed_file(self, effect_name: str, raw_path: str) -> None:
        target = self._managed_file(effect_name, raw_path)
        if target is None:
            return
        try:
            target.unlink()
        except OSError:
            pass

    def _managed_asset_digests(
        self, effect_name: str, raw_paths: Sequence[Any] | None
    ) -> set[str]:
        """Fingerprint assets already stored for one effect.

        The same asset may only appear once per field. Uploading a byte-identical
        file under a new name must not create a second playback entry.
        """
        digests: set[str] = set()
        for raw_path in raw_paths or ():
            target = self._managed_file(effect_name, str(raw_path))
            if target is None:
                continue
            digest = _file_digest(target)
            if digest:
                digests.add(digest)
        return digests

    @staticmethod
    def _available_destination(directory: Path, filename: str) -> Path:
        destination = safe_child_path(directory, safe_filename(filename))
        counter = 1
        stem = destination.stem
        suffix = destination.suffix
        while destination.exists():
            destination = directory / f"{stem}_{counter}{suffix}"
            counter += 1
        return destination

    def _renamed_asset_paths(
        self,
        raw_paths: Any,
        old_dir: Path,
        new_dir: Path,
    ) -> list[Any]:
        if not isinstance(raw_paths, list):
            return list(raw_paths or [])
        old_root = old_dir.resolve(strict=False)
        updated: list[Any] = []
        for raw_path in raw_paths:
            if not isinstance(raw_path, str):
                updated.append(raw_path)
                continue
            try:
                relative = self._configured_path(raw_path).relative_to(old_root)
            except (OSError, RuntimeError, ValueError):
                updated.append(raw_path)
            else:
                updated.append((new_dir / relative).as_posix())
        return updated

    def _configured_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        windows_path = PureWindowsPath(raw_path)
        if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
            return path.resolve(strict=False)
        return safe_child_path(self.project_root, path)

    @staticmethod
    def _move_effect_dir(old_dir: Path, new_dir: Path) -> None:
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            old_dir.rename(new_dir)
        except OSError:
            new_dir.mkdir(parents=True, exist_ok=True)
            for item in old_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, safe_child_path(new_dir, item.name))
            shutil.rmtree(old_dir, ignore_errors=True)

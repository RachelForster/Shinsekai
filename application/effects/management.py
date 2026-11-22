"""Application use case for effect configuration and managed media resources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Any, Sequence, TypeAlias

from application.media.resource_paths import MediaResourcePaths
from config.schema import Effect
from core.effects.ops import (
    CatalogEffectTarget,
    ConfigManagerEffectTarget,
    EffectPersistenceTarget,
    delete_all_effect_audio_op,
    delete_effect_ambient_op,
    delete_effect_audio_op,
    delete_effect_image_op,
    delete_effect_op,
    import_effect_packages_op,
    save_effect_ambient_layers_op,
    save_effect_ambient_tags_op,
    save_effect_audio_tags_op,
    save_effect_image_tags_op,
    save_effect_op,
    upload_effect_ambient_audio_op,
    upload_effect_ambient_op,
    upload_effect_audio_op,
    upload_effect_image_audio_op,
    upload_effect_images_op,
)
from core.effects.paths import validate_effect_storage_name
from core.packaging.effect_package import export_effect_package
from core.storage.layout import StorageLayout
from core.storage.stores import EffectCatalogPort


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
        self.layout = StorageLayout(project_root or Path.cwd())
        self.project_root = self.layout.project_root
        self.local_file_access_roots = tuple(
            Path(root).resolve(strict=False) for root in local_file_access_roots
        )
        self._resource_paths = MediaResourcePaths(
            self.project_root,
            file_access_roots=self.local_file_access_roots,
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
        return self.layout.media_dir("effects")

    def _target(self) -> EffectPersistenceTarget:
        if self.effects is not None:
            return CatalogEffectTarget(self.effects, self.config_manager)
        return ConfigManagerEffectTarget(self.config_manager)

    def _save(self, payload: dict[str, Any]) -> Effect:
        return save_effect_op(self._target(), self.layout, payload)

    def _delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        return delete_effect_op(
            self._target(),
            self.layout,
            str(payload.get("name") or ""),
        )

    def _upload_audio(self, payload: dict[str, Any]) -> Effect:
        return upload_effect_audio_op(
            self._target(),
            self.layout,
            local_file_access_roots=self.local_file_access_roots,
            name=str(payload.get("name") or ""),
            paths=payload.get("paths") or [],
            audio_tags=payload.get("audioTags") or "",
        )

    def _delete_audio(self, payload: dict[str, Any]) -> Effect:
        return delete_effect_audio_op(
            self._target(),
            self.layout,
            name=str(payload.get("name") or ""),
            index=int(payload.get("index") or 0),
        )

    def _delete_all_audio(self, payload: dict[str, Any]) -> Effect:
        return delete_all_effect_audio_op(
            self._target(),
            self.layout,
            name=str(payload.get("name") or ""),
        )

    def _save_audio_tags(self, payload: dict[str, Any]) -> Effect:
        return save_effect_audio_tags_op(
            self._target(),
            name=str(payload.get("name") or ""),
            audio_tags=str(payload.get("audioTags") or ""),
        )

    def _upload_images(self, payload: dict[str, Any]) -> Effect:
        return upload_effect_images_op(
            self._target(),
            self.layout,
            local_file_access_roots=self.local_file_access_roots,
            name=str(payload.get("name") or ""),
            paths=payload.get("paths") or [],
            image_tags=payload.get("imageTags") or "",
        )

    def _delete_image(self, payload: dict[str, Any]) -> Effect:
        return delete_effect_image_op(
            self._target(),
            self.layout,
            name=str(payload.get("name") or ""),
            index=int(payload.get("index") or 0),
        )

    def _save_image_tags(self, payload: dict[str, Any]) -> Effect:
        return save_effect_image_tags_op(
            self._target(),
            name=str(payload.get("name") or ""),
            image_tags=str(payload.get("imageTags") or ""),
        )

    def _upload_image_audio(self, payload: dict[str, Any]) -> Effect:
        return upload_effect_image_audio_op(
            self._target(),
            self.layout,
            local_file_access_roots=self.local_file_access_roots,
            name=str(payload.get("name") or ""),
            index=int(payload.get("index") or 0),
            raw_path=str(payload.get("path") or ""),
        )

    def _upload_ambient(self, payload: dict[str, Any]) -> Effect:
        return upload_effect_ambient_op(
            self._target(),
            self.layout,
            local_file_access_roots=self.local_file_access_roots,
            name=str(payload.get("name") or ""),
            paths=payload.get("paths") or [],
            ambient_tags=payload.get("ambientTags") or "",
        )

    def _delete_ambient(self, payload: dict[str, Any]) -> Effect:
        return delete_effect_ambient_op(
            self._target(),
            self.layout,
            name=str(payload.get("name") or ""),
            index=int(payload.get("index") or 0),
        )

    def _save_ambient_tags(self, payload: dict[str, Any]) -> Effect:
        return save_effect_ambient_tags_op(
            self._target(),
            name=str(payload.get("name") or ""),
            ambient_tags=str(payload.get("ambientTags") or ""),
        )

    def _save_ambient_layers(self, payload: dict[str, Any]) -> Effect:
        return save_effect_ambient_layers_op(
            self._target(),
            name=str(payload.get("name") or ""),
            raw_layers=payload.get("layers") or [],
        )

    def _upload_ambient_audio(self, payload: dict[str, Any]) -> Effect:
        return upload_effect_ambient_audio_op(
            self._target(),
            self.layout,
            local_file_access_roots=self.local_file_access_roots,
            name=str(payload.get("name") or ""),
            index=int(payload.get("index") or 0),
            raw_path=str(payload.get("path") or ""),
        )

    def _import(self, payload: dict[str, Any]) -> list[Effect]:
        return import_effect_packages_op(
            self._target(),
            self.layout,
            local_file_access_roots=self.local_file_access_roots,
            paths=payload.get("paths") or [],
        )

    def _export(self, payload: dict[str, Any]) -> EffectExportResult:
        name = validate_effect_storage_name(str(payload.get("name") or ""))
        effect = self._target().get_by_name(name)
        if effect is None:
            raise KeyError(f"effect not found: {name}")
        output, relative_path = self._resource_paths.export_target(name, ".ef")
        export_effect_package(
            effect,
            output,
            effect_root=self.effect_root,
            project_root=self.project_root,
            local_file_access_roots=self.local_file_access_roots,
        )
        return EffectExportResult(relative_path)

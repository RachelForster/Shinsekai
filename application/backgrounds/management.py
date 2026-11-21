"""Background resource-management use cases.

The HTTP bridge owns request/response transport.  This module owns operations
that combine background configuration with managed files or package I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from application.media.resource_paths import MediaResourcePaths
from application.runtime.state import _jsonify


class BackgroundOperation(str, Enum):
    SAVE = "save"
    SAVE_IMAGE_TAGS = "save-image-tags"
    SAVE_BGM_TAGS = "save-bgm-tags"
    DELETE = "delete"
    UPLOAD_IMAGES = "upload-images"
    UPLOAD_BGM = "upload-bgm"
    DELETE_IMAGE = "delete-image"
    DELETE_ALL_IMAGES = "delete-all-images"
    DELETE_BGM = "delete-bgm"
    DELETE_ALL_BGM = "delete-all-bgm"
    IMPORT = "import"
    EXPORT = "export"


@dataclass(frozen=True)
class BackgroundRequest:
    operation: BackgroundOperation
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BackgroundExportResult:
    """Transport-neutral reference to an exported background package."""

    path: str


def parse_background_request(
    operation: BackgroundOperation,
    payload: dict[str, Any],
) -> BackgroundRequest:
    if not isinstance(payload, dict):
        raise ValueError("background payload must be an object")
    return BackgroundRequest(operation=operation, payload=dict(payload))


class BackgroundUseCase:
    """Single application entry point for background resource mutations."""

    def __init__(
        self,
        state: Any,
        *,
        file_access_roots: Iterable[Path] = (),
        backgrounds: Any | None = None,
    ):
        self._state = state
        self._backgrounds = backgrounds or getattr(getattr(state, "stores", None), "backgrounds", None)
        project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
        self._resource_paths = MediaResourcePaths(
            project_root,
            file_access_roots=file_access_roots,
        )

    def execute(self, request: BackgroundRequest) -> Any:
        handlers = {
            BackgroundOperation.SAVE: self._save,
            BackgroundOperation.SAVE_IMAGE_TAGS: self._save_image_tags,
            BackgroundOperation.SAVE_BGM_TAGS: self._save_bgm_tags,
            BackgroundOperation.DELETE: self._delete,
            BackgroundOperation.UPLOAD_IMAGES: self._upload_images,
            BackgroundOperation.UPLOAD_BGM: self._upload_bgm,
            BackgroundOperation.DELETE_IMAGE: self._delete_image,
            BackgroundOperation.DELETE_ALL_IMAGES: self._delete_all_images,
            BackgroundOperation.DELETE_BGM: self._delete_bgm,
            BackgroundOperation.DELETE_ALL_BGM: self._delete_all_bgm,
            BackgroundOperation.IMPORT: self._import_packages,
            BackgroundOperation.EXPORT: self._export_package,
        }
        return handlers[request.operation](request.payload)

    def _background(self, name: str) -> Any:
        if self._backgrounds is not None:
            background = self._backgrounds.get_by_name(name)
        else:
            background = self._state.config_manager.get_background_by_name(name)
        if background is None:
            raise KeyError(f"background not found: {name}")
        return background

    def _refresh_backgrounds_catalog(self) -> None:
        refresh = getattr(self._state.config_manager, "refresh_backgrounds", None)
        if callable(refresh):
            refresh()
        else:
            self._state.config_manager.reload()

    def _after_reload(self, name: str) -> dict[str, Any]:
        self._refresh_backgrounds_catalog()
        return _jsonify(self._background(name))

    def _files(self, raw_paths: Any) -> list[Any]:
        return [
            SimpleNamespace(name=str(path))
            for path in self._resource_paths.input_files(
                raw_paths,
                field="background file",
            )
        ]

    def _save(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = payload.get("background", payload)
        if not isinstance(body, dict):
            raise ValueError("background payload must be an object")
        name = str(body.get("name") or "").strip()
        prefix = str(body.get("sprite_prefix") or "temp").strip() or "temp"
        original_name = str(payload.get("originalName") or "").strip()
        message, _names = self._state.background_manager.add_background(
            name,
            prefix,
            edit_as_name=original_name or None,
            bg_tags=str(body.get("bg_tags") or ""),
            bgm_tags=str(body.get("bgm_tags") or ""),
        )
        if message.startswith("名称") or "重复" in message or message.startswith("找不到"):
            raise RuntimeError(message)
        self._refresh_backgrounds_catalog()
        saved = self._state.config_manager.get_background_by_name(name)
        if saved is None:
            raise RuntimeError(message)
        return _jsonify(saved)

    def _persist_background(self, background: Any) -> None:
        if self._backgrounds is not None and getattr(background, "id", None):
            self._backgrounds.put(background.id, background)
        else:
            self._state.config_manager.save_background_config()

    def _save_image_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("background name is required")
        background = self._background(name)
        background.bg_tags = str(payload.get("bgTags") or "")
        self._persist_background(background)
        return self._after_reload(name)

    def _save_bgm_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("background name is required")
        background = self._background(name)
        background.bgm_tags = str(payload.get("bgmTags") or "")
        self._persist_background(background)
        return self._after_reload(name)

    def _delete(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, names = self._state.background_manager.delete_background(name)
        if message.startswith("找不到") or message.startswith("请选择") or "失败" in message:
            raise RuntimeError(message)
        return {"message": message, "names": names}

    def _upload_images(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.background_manager.upload_sprites(
            name,
            self._files(payload.get("paths") or []),
            str(payload.get("bgTags") or ""),
        )
        if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _upload_bgm(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        files = self._files(payload.get("paths") or [])
        background = self._background(name)
        background.bgm_tags = str(payload.get("bgmTags") or background.bgm_tags or "")
        self._state.config_manager.save_background_config()
        message, _dataframe, _tags = self._state.background_manager.upload_bgms(name, files)
        if message.startswith("找不到") or message.startswith("请选择") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _delete_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.background_manager.delete_single_sprite(
            name,
            int(payload.get("index") or 0),
        )
        if message.startswith("找不到") or message.startswith("背景图片不存在") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _delete_all_images(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.background_manager.delete_all_sprites(name)
        if message.startswith("找不到") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _delete_bgm(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.background_manager.delete_single_bgm(
            name,
            int(payload.get("index") or 0),
        )
        if message.startswith("找不到") or message.startswith("背景音乐不存在") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _delete_all_bgm(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        message, _paths, _tags = self._state.background_manager.delete_all_bgms(name)
        if message.startswith("找不到") or message.startswith("请先"):
            raise RuntimeError(message)
        return self._after_reload(name)

    def _import_packages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        files = self._files(payload.get("paths") or [])
        from core.packaging.background_package import stage_background_package_import
        from core.packaging.zip_io import rollback_staged_assets
        from tools import file_util

        stores = getattr(self._state, "stores", None)
        project_root = self._resource_paths.project_root
        default_data = Path("./data")
        bg_upload_dir = (
            Path(file_util.BACKGROUND_UPLOAD_DIR)
            if file_util.BACKGROUND_UPLOAD_DIR != default_data / "backgrounds"
            else (stores.layout.media_dir("backgrounds") if stores is not None else project_root / "data" / "backgrounds")
        )
        bgm_upload_dir = (
            Path(file_util.BGM_UPLOAD_DIR)
            if file_util.BGM_UPLOAD_DIR != default_data / "bgm"
            else (stores.layout.media_dir("bgm") if stores is not None else project_root / "data" / "bgm")
        )

        existing = list(
            stores.backgrounds.list_all()
            if stores is not None
            else self._state.config_manager.config.background_list
        )
        imported = []
        created_dirs: list[Path] = []
        committed = False
        try:
            for item in files:
                staged = stage_background_package_import(
                    item.name,
                    existing_configs=[*existing, *imported],
                    background_upload_dir=bg_upload_dir,
                    bgm_upload_dir=bgm_upload_dir,
                )
                created_dirs.extend(staged.created_dirs)
                imported.extend(staged.backgrounds)

            if stores is not None:
                with stores.main_db.atomic():
                    for bg in imported:
                        stores.backgrounds.put(bg.id, bg)
                committed = True
                self._refresh_backgrounds_catalog()
            else:
                target_list = self._state.config_manager.config.background_list
                for background in imported:
                    if background not in target_list:
                        target_list.append(background)
                self._state.config_manager.save_background_config()
                committed = True
                self._refresh_backgrounds_catalog()
            return [_jsonify(item) for item in imported]
        except BaseException:
            if not committed:
                rollback_staged_assets(created_dirs)
            raise

    def _export_package(self, payload: dict[str, Any]) -> BackgroundExportResult:
        name = str(payload.get("name") or "")
        background = self._background(name)
        output, relative = self._resource_paths.export_target(name, ".bg")
        from tools.file_util import export_background

        export_background([background], output.as_posix(), open_folder=False)
        return BackgroundExportResult(path=relative)

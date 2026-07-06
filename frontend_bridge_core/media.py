from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from frontend_bridge_core.backgrounds import (
    _delete_all_background_bgm,
    _delete_all_background_images,
    _delete_background_bgm,
    _delete_background_image,
    _save_background,
    _save_background_bgm_tags,
    _save_background_image_tags,
    _translate_background_fields,
    _upload_background_bgm,
    _upload_background_images,
)
from frontend_bridge_core.characters import (
    _as_character_config,
    _delete_all_character_sprites,
    _delete_character_sprite,
    _delete_sprite_voice,
    _generate_character_setting,
    _save_character,
    _save_character_emotion_tags,
    _save_sprite_scale,
    _save_sprite_voice_text,
    _translate_character_fields,
    _upload_character_sprites,
    _upload_sprite_voice,
)
from frontend_bridge_core.memory import _add_character_memory, _delete_character_memory, _list_character_memories
from frontend_bridge_core.security import safe_child_path, safe_existing_file_path


def _media_thumbnail(source: Path, *, project_root: Path, size: int = 160) -> Path:
    source = safe_existing_file_path(source, field="media source")
    if not source.is_file():
        raise FileNotFoundError(source.as_posix())

    stat = source.stat()
    target_size = max(32, min(int(size), 512))
    digest = hashlib.sha256(
        f"{source.resolve()}\0{stat.st_mtime_ns}\0{stat.st_size}\0{target_size}".encode(
            "utf-8",
            errors="surrogatepass",
        )
    ).hexdigest()
    cache_root = project_root / ".cache" / "frontend-media-thumbnails"
    cache_path = safe_child_path(cache_root, f"{digest}.png")
    if cache_path.is_file():
        return cache_path

    from PIL import Image, ImageOps

    cache_root.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        thumbnail = ImageOps.exif_transpose(image)
        if thumbnail.mode not in {"RGB", "RGBA"}:
            thumbnail = thumbnail.convert(
                "RGBA" if "A" in thumbnail.getbands() else "RGB",
            )
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        thumbnail.thumbnail((target_size, target_size), resampling)

        with tempfile.NamedTemporaryFile(
            dir=cache_root,
            prefix=f"{digest}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
        try:
            thumbnail.save(tmp_path, format="PNG", optimize=True)
            tmp_path.replace(cache_path)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return cache_path


def _thumbnail_cache_path(thumbnail: Path, project_root: Path) -> str:
    try:
        return thumbnail.relative_to(project_root).as_posix()
    except ValueError:
        return thumbnail.as_posix()


def _media_thumbnail_data_url(source: Path, *, project_root: Path, size: int = 160) -> str:
    thumbnail = _media_thumbnail(source, project_root=project_root, size=size)
    mime_type = mimetypes.guess_type(thumbnail.name)[0] or "image/png"
    raw = thumbnail.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _media_thumbnail_batch(
    items: list[tuple[str, Path]],
    *,
    include_data_url: bool = True,
    project_root: Path,
    size: int = 160,
) -> dict[str, Any]:
    if not items:
        return {"items": []}

    unique_items: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for raw_path, source in items:
        if raw_path in seen:
            continue
        seen.add(raw_path)
        unique_items.append((raw_path, source))

    max_workers = max(2, min(8, os.cpu_count() or 2, len(unique_items)))

    def build_item(item: tuple[str, Path]) -> dict[str, Any]:
        raw_path, source = item
        try:
            thumbnail = _media_thumbnail(source, project_root=project_root, size=size)
            payload = {
                "cachePath": _thumbnail_cache_path(thumbnail, project_root),
                "mimeType": mimetypes.guess_type(thumbnail.name)[0] or "image/png",
                "path": raw_path,
            }
            if include_data_url:
                raw = thumbnail.read_bytes()
                encoded = base64.b64encode(raw).decode("ascii")
                payload["dataUrl"] = f"data:{payload['mimeType']};base64,{encoded}"
            return payload
        except Exception as exc:
            return {
                "error": str(exc),
                "path": raw_path,
                "type": exc.__class__.__name__,
            }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(build_item, unique_items))
    return {"items": results}


__all__ = [
    "_add_character_memory",
    "_as_character_config",
    "_delete_all_background_bgm",
    "_delete_all_background_images",
    "_delete_all_character_sprites",
    "_delete_background_bgm",
    "_delete_background_image",
    "_delete_character_memory",
    "_delete_character_sprite",
    "_delete_sprite_voice",
    "_generate_character_setting",
    "_list_character_memories",
    "_media_thumbnail",
    "_media_thumbnail_batch",
    "_media_thumbnail_data_url",
    "_thumbnail_cache_path",
    "_save_background",
    "_save_background_bgm_tags",
    "_save_background_image_tags",
    "_save_character",
    "_save_character_emotion_tags",
    "_save_sprite_scale",
    "_save_sprite_voice_text",
    "_translate_background_fields",
    "_translate_character_fields",
    "_upload_background_bgm",
    "_upload_background_images",
    "_upload_character_sprites",
    "_upload_sprite_voice",
]

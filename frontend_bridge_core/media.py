from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from .backgrounds import (
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
from .characters import (
    _add_character_memory,
    _as_character_config,
    _delete_all_character_sprites,
    _delete_character_memory,
    _delete_character_sprite,
    _delete_sprite_voice,
    _generate_character_setting,
    _list_character_memories,
    _save_character,
    _save_character_emotion_tags,
    _save_sprite_scale,
    _save_sprite_voice_text,
    _translate_character_fields,
    _upload_character_sprites,
    _upload_sprite_voice,
)


def _media_thumbnail(source: Path, *, project_root: Path, size: int = 160) -> Path:
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
    cache_path = cache_root / f"{digest}.png"
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

"""Image auto-annotation application use cases."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ai.vision import configured_vision_manager
from application.media.sprite_tags import SPRITE_TAG_INSTRUCTIONS, normalize_sprite_tags
from core.media.asset_tags import normalize_generated_tags, numbered_tags, tag_contents


ProgressCallback = Callable[[int, int, str, str], None]
CancelCallback = Callable[[], bool]
InferCallback = Callable[[bytes, str], str]

CHARACTER_PROMPT = (
    "你在为对话系统标注角色立绘。请根据图片中可见的表情和姿态标注，不要根据角色设定猜测。"
    + SPRITE_TAG_INSTRUCTIONS
)
BACKGROUND_PROMPT = (
    "Generate concise English tags for this background image. Focus on location, time of day, weather, "
    "lighting, atmosphere, and important objects. Output only comma-separated tags: no numbering and "
    "no full sentences."
)
_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp", ".mp4", ".webm"}


class AnnotationCancelled(RuntimeError):
    pass


def _sprite_path(sprite: object) -> str:
    if isinstance(sprite, dict):
        return str(sprite.get("path") or "")
    return str(getattr(sprite, "path", "") or "")


def _safe_asset_file(raw_path: str, project_root: Path) -> Path:
    if not raw_path.strip() or any(ord(char) < 32 for char in raw_path):
        raise ValueError("图片路径无效")
    root = project_root.resolve()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=True)
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise PermissionError("图片路径超出项目目录")
    if not resolved.is_file() or resolved.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError("不是受支持的图片文件")
    return resolved


def _annotation_image_bytes(path: Path, project_root: Path) -> bytes:
    if path.suffix.lower() not in {".mp4", ".webm"}:
        return path.read_bytes()
    from core.media.video_frames import extract_video_frame

    cache = project_root.resolve() / "cache" / "vision_annotations"
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / f"{uuid.uuid4().hex}.png"
    try:
        extract_video_frame(path, output)
        return output.read_bytes()
    finally:
        output.unlink(missing_ok=True)


def annotate_unlabelled_images(
    sprites: Sequence[object],
    tag_block: str,
    *,
    prefix: str,
    prompt: str,
    project_root: Path,
    infer: InferCallback | None = None,
    api_config: Any | None = None,
    normalize: Callable[[str], str] = normalize_generated_tags,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> dict[str, Any]:
    tags = tag_contents(tag_block, len(sprites))
    missing_indexes = [index for index, tag in enumerate(tags) if not tag.strip()]
    failures: list[dict[str, Any]] = []
    annotated = 0
    runner = infer

    for completed, index in enumerate(missing_indexes):
        if is_cancelled and is_cancelled():
            raise AnnotationCancelled("图片智能标注已取消")
        try:
            image_path = _safe_asset_file(_sprite_path(sprites[index]), project_root)
            first_inference = runner is None or completed == 0
            if runner is None:
                runner = configured_vision_manager(api_config=api_config).describe
            if on_progress:
                if first_inference:
                    on_progress(
                        completed,
                        len(missing_indexes),
                        f"正在连接已配置的视觉服务，并标注第 {completed + 1}/{len(missing_indexes)} 张图片…",
                        "loading-model",
                    )
                else:
                    on_progress(
                        completed,
                        len(missing_indexes),
                        f"正在智能标注第 {completed + 1}/{len(missing_indexes)} 张图片…",
                        "annotating",
                    )
            image_bytes = _annotation_image_bytes(image_path, project_root)
            raw = runner(image_bytes, prompt)
            try:
                generated = normalize(raw)
            except ValueError:
                if is_cancelled and is_cancelled():
                    raise AnnotationCancelled("图片智能标注已取消")
                retry = (
                    prompt
                    + "\n上次输出不符合格式，请重新看图并严格按要求回答。上次输出："
                    + json.dumps(raw, ensure_ascii=False)
                )
                generated = normalize(runner(image_bytes, retry))
            if not generated:
                raise ValueError("视觉模型未返回标签")
            tags[index] = generated
            annotated += 1
            message = f"已标注 {prefix} {index + 1}"
        except (OSError, PermissionError, ValueError) as exc:
            failures.append({"index": index, "message": str(exc)})
            message = f"跳过 {prefix} {index + 1}：{exc}"
        if on_progress:
            on_progress(completed + 1, len(missing_indexes), message, "annotating")

    return {
        "annotatedCount": annotated,
        "failedCount": len(failures),
        "failures": failures,
        "skippedCount": len(sprites) - len(missing_indexes),
        "tags": numbered_tags(prefix, tags),
        "totalCount": len(sprites),
    }


def auto_label_character_sprites(
    config_manager: object,
    name: str,
    *,
    project_root: Path,
    infer: InferCallback | None = None,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> dict[str, Any]:
    character = config_manager.get_character_by_name(name)  # type: ignore[attr-defined]
    if character is None:
        raise KeyError(f"角色不存在：{name}")
    result = annotate_unlabelled_images(
        character.sprites,
        character.emotion_tags,
        prefix="立绘",
        prompt=CHARACTER_PROMPT,
        project_root=project_root,
        infer=infer,
        api_config=getattr(getattr(config_manager, "config", None), "api_config", None),
        normalize=normalize_sprite_tags,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )
    if result["annotatedCount"]:
        character.emotion_tags = result["tags"]
        config_manager.save_characters_config()  # type: ignore[attr-defined]
    return {**result, "name": character.name, "scope": "character"}


def auto_label_background_images(
    config_manager: object,
    name: str,
    *,
    project_root: Path,
    infer: InferCallback | None = None,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> dict[str, Any]:
    background = config_manager.get_background_by_name(name)  # type: ignore[attr-defined]
    if background is None:
        raise KeyError(f"背景不存在：{name}")
    result = annotate_unlabelled_images(
        background.sprites,
        background.bg_tags,
        prefix="场景",
        prompt=BACKGROUND_PROMPT,
        project_root=project_root,
        infer=infer,
        api_config=getattr(getattr(config_manager, "config", None), "api_config", None),
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )
    if result["annotatedCount"]:
        background.bg_tags = result["tags"]
        config_manager.save_background_config()  # type: ignore[attr-defined]
    return {**result, "name": background.name, "scope": "background"}

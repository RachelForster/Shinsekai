"""Image auto-annotation application use cases."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ai.llm.template.generation.media_annotation import (
    render_annotation_retry_prompt,
    render_background_annotation_prompt,
    render_character_annotation_prompt,
)
from ai.llm.template.integrations.localization import (
    LocaleInput,
    resolve_dynamic_locale,
)
from ai.vision import configured_vision_manager
from application.media.sprite_tags import normalize_sprite_tags
from core.media.asset_tags import normalize_generated_tags, numbered_tags, tag_contents


ProgressCallback = Callable[[int, int, str, str], None]
CancelCallback = Callable[[], bool]
InferCallback = Callable[[bytes, str], str]

CHARACTER_PROMPT = render_character_annotation_prompt()
BACKGROUND_PROMPT = render_background_annotation_prompt(locale="en")
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
    locale: LocaleInput = None,
) -> dict[str, Any]:
    effective_locale = resolve_dynamic_locale(locale) if locale is not None else "zh_CN"
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
                retry = render_annotation_retry_prompt(
                    prompt,
                    raw,
                    locale=effective_locale,
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


def _merge_newly_annotated_tags(
    original_sprites: Sequence[Any],
    original_tag_block: str,
    generated_tag_block: str,
    latest_sprites: Sequence[Any],
    latest_tag_block: str,
    *,
    prefix: str,
) -> str:
    """Apply newly generated tags onto still-unlabelled slots of the latest row snapshot."""
    orig_tags = tag_contents(original_tag_block, len(original_sprites))
    gen_tags = tag_contents(generated_tag_block, len(original_sprites))
    latest_tags = tag_contents(latest_tag_block, len(latest_sprites))
    latest_paths = [_sprite_path(sprite) for sprite in latest_sprites]

    for idx, (old_tag, gen_tag) in enumerate(zip(orig_tags, gen_tags)):
        if old_tag.strip() or not gen_tag.strip():
            continue
        orig_path = _sprite_path(original_sprites[idx])
        if (
            0 <= idx < len(latest_sprites)
            and latest_paths[idx] == orig_path
            and not latest_tags[idx].strip()
        ):
            latest_tags[idx] = gen_tag
            continue
        for fallback_idx, candidate_path in enumerate(latest_paths):
            if candidate_path == orig_path and not latest_tags[fallback_idx].strip():
                latest_tags[fallback_idx] = gen_tag
                break
    return numbered_tags(prefix, latest_tags)


def auto_label_character_sprites(
    config_manager: object,
    name: str,
    *,
    project_root: Path,
    infer: InferCallback | None = None,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
    characters: Any = None,
) -> dict[str, Any]:
    from config.character_ops import CHARACTER_MUTATION_LOCK, save_character_emotion_tags_op

    character = (
        characters.get_by_name(name)
        if characters is not None
        else config_manager.get_character_by_name(name)  # type: ignore[attr-defined]
    )
    if character is None:
        raise KeyError(f"角色不存在：{name}")
    char_id = str(getattr(character, "id", "") or "").strip()
    original_sprites = list(character.sprites or [])
    original_tags = str(character.emotion_tags or "")
    result = annotate_unlabelled_images(
        original_sprites,
        original_tags,
        prefix="立绘",
        prompt=CHARACTER_PROMPT,
        project_root=project_root,
        infer=infer,
        api_config=getattr(getattr(config_manager, "config", None), "api_config", None),
        normalize=normalize_sprite_tags,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )
    resolved_name = str(character.name)
    merged_tags = str(result["tags"])
    if result["annotatedCount"]:
        with CHARACTER_MUTATION_LOCK:
            if characters is not None:
                from application.characters.management import _CatalogCharacterTarget

                latest = (characters.get(char_id) if char_id else None) or characters.get_by_name(name)
                if latest is None:
                    raise KeyError(f"角色不存在：{name}")
                merged_tags = _merge_newly_annotated_tags(
                    original_sprites,
                    original_tags,
                    result["tags"],
                    list(latest.sprites or []),
                    str(latest.emotion_tags or ""),
                    prefix="立绘",
                )
                save_character_emotion_tags_op(
                    _CatalogCharacterTarget(characters),
                    latest.name,
                    merged_tags,
                )
                refresh = getattr(config_manager, "refresh_characters", None)
                if callable(refresh):
                    refresh()
                resolved_name = str(latest.name)
            else:
                latest = config_manager.get_character_by_name(name) or character  # type: ignore[attr-defined]
                merged_tags = _merge_newly_annotated_tags(
                    original_sprites,
                    original_tags,
                    result["tags"],
                    list(latest.sprites or []),
                    str(latest.emotion_tags or ""),
                    prefix="立绘",
                )
                latest.emotion_tags = merged_tags
                config_manager.save_characters_config()  # type: ignore[attr-defined]
                resolved_name = str(latest.name)
    return {**result, "tags": merged_tags, "name": resolved_name, "scope": "character"}


def auto_label_background_images(
    config_manager: object,
    name: str,
    *,
    project_root: Path,
    infer: InferCallback | None = None,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
    backgrounds: Any = None,
) -> dict[str, Any]:
    from config.background_ops import BACKGROUND_MUTATION_LOCK, save_background_image_tags_op

    background = (
        backgrounds.get_by_name(name)
        if backgrounds is not None
        else config_manager.get_background_by_name(name)  # type: ignore[attr-defined]
    )
    if background is None:
        raise KeyError(f"背景不存在：{name}")
    effective_locale = resolve_dynamic_locale(config_manager=config_manager)
    bg_id = str(getattr(background, "id", "") or "").strip()
    original_sprites = list(background.sprites or [])
    original_tags = str(background.bg_tags or "")
    result = annotate_unlabelled_images(
        original_sprites,
        original_tags,
        prefix="场景",
        prompt=render_background_annotation_prompt(locale=effective_locale),
        project_root=project_root,
        infer=infer,
        api_config=getattr(getattr(config_manager, "config", None), "api_config", None),
        on_progress=on_progress,
        is_cancelled=is_cancelled,
        locale=effective_locale,
    )
    resolved_name = str(background.name)
    merged_tags = str(result["tags"])
    if result["annotatedCount"]:
        with BACKGROUND_MUTATION_LOCK:
            if backgrounds is not None:
                from application.backgrounds.management import _CatalogBackgroundTarget

                latest = (backgrounds.get(bg_id) if bg_id else None) or backgrounds.get_by_name(name)
                if latest is None:
                    raise KeyError(f"背景不存在：{name}")
                merged_tags = _merge_newly_annotated_tags(
                    original_sprites,
                    original_tags,
                    result["tags"],
                    list(latest.sprites or []),
                    str(latest.bg_tags or ""),
                    prefix="场景",
                )
                save_background_image_tags_op(
                    _CatalogBackgroundTarget(backgrounds),
                    latest.name,
                    merged_tags,
                )
                refresh = getattr(config_manager, "refresh_backgrounds", None)
                if callable(refresh):
                    refresh()
                resolved_name = str(latest.name)
            else:
                latest = config_manager.get_background_by_name(name) or background  # type: ignore[attr-defined]
                merged_tags = _merge_newly_annotated_tags(
                    original_sprites,
                    original_tags,
                    result["tags"],
                    list(latest.sprites or []),
                    str(latest.bg_tags or ""),
                    prefix="场景",
                )
                latest.bg_tags = merged_tags
                config_manager.save_background_config()  # type: ignore[attr-defined]
                resolved_name = str(latest.name)
    return {**result, "tags": merged_tags, "name": resolved_name, "scope": "background"}

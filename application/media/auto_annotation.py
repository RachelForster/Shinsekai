from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ai.vision import VisionManager
from sdk.file_transactions import (
    open_binary_read_without_links,
    read_bytes_without_links,
)
from core.media.asset_tags import normalize_generated_tags, numbered_tags, tag_contents
from sdk.path_contract import (
    relative_path_has_prefix,
    resolve_managed_project_path,
    resolve_project_path,
    resolve_runtime_asset_read_path,
)


ProgressCallback = Callable[[int, int, str, str], None]
CancelCallback = Callable[[], bool]
InferCallback = Callable[[bytes, str], str]

CHARACTER_PROMPT = (
    "Generate concise English tags for this character sprite. Focus on facial expression, emotion, pose, "
    "clothing, and visual state. Output only comma-separated tags: no numbering, no full sentences, "
    "and no guesses about the character's identity."
)
BACKGROUND_PROMPT = (
    "Generate concise English tags for this background image. Focus on location, time of day, weather, "
    "lighting, atmosphere, and important objects. Output only comma-separated tags: no numbering and "
    "no full sentences."
)
_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


class AnnotationCancelled(RuntimeError):
    pass


def _sprite_path(sprite: object) -> str:
    if isinstance(sprite, dict):
        return str(sprite.get("path") or "")
    return str(getattr(sprite, "path", "") or "")


def _safe_asset_file(
    raw_path: str,
    project_root: Path,
) -> tuple[Path, os.stat_result]:
    if (
        not raw_path
        or raw_path != raw_path.strip()
        or any(
            ord(char) < 32
            or ord(char) == 127
            or 0xD800 <= ord(char) <= 0xDFFF
            for char in raw_path
        )
    ):
        raise ValueError("图片路径无效")
    root = resolve_project_path(".", root=project_root)
    try:
        if (
            not Path(raw_path).expanduser().is_absolute()
            and relative_path_has_prefix(
                raw_path,
                (("assets",),),
                field="image path",
            )
        ):
            resolved = resolve_runtime_asset_read_path(
                raw_path,
                root=root,
            )
        else:
            resolved = resolve_managed_project_path(raw_path, root=root)
    except PermissionError as exc:
        raise PermissionError("图片路径超出项目目录") from exc
    if not resolved.is_file() or resolved.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError("不是受支持的图片文件")
    with open_binary_read_without_links(resolved) as source:
        identity = os.fstat(source.fileno())
    return resolved, identity


def annotate_unlabelled_images(
    sprites: Sequence[object],
    tag_block: str,
    *,
    prefix: str,
    prompt: str,
    project_root: Path,
    infer: InferCallback | None = None,
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
            raise AnnotationCancelled("图片自动标注已取消")
        try:
            image_path, image_identity = _safe_asset_file(
                _sprite_path(sprites[index]),
                project_root,
            )
            first_inference = runner is None or completed == 0
            if runner is None:
                runner = VisionManager(
                    "moondream",
                    root=project_root,
                ).describe
            if on_progress:
                if first_inference:
                    on_progress(
                        completed,
                        len(missing_indexes),
                        f"正在加载 Moondream 模型并准备标注第 {completed + 1}/{len(missing_indexes)} 张图片…",
                        "loading-model",
                    )
                else:
                    on_progress(
                        completed,
                        len(missing_indexes),
                        f"正在标注第 {completed + 1}/{len(missing_indexes)} 张图片…",
                        "annotating",
                    )
            generated = normalize_generated_tags(
                runner(
                    read_bytes_without_links(
                        image_path,
                        expected_identity=image_identity,
                    ),
                    prompt,
                )
            )
            if not generated:
                raise ValueError("Moondream 未返回标签")
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
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )
    if result["annotatedCount"]:
        background.bg_tags = result["tags"]
        config_manager.save_background_config()  # type: ignore[attr-defined]
    return {**result, "name": background.name, "scope": "background"}

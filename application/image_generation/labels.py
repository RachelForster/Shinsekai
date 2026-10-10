"""Label generated sprite files without changing a saved character."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.vision import configured_vision_available, configured_vision_manager
from application.media.auto_annotation import (
    AnnotationCancelled,
    CancelCallback,
    CHARACTER_PROMPT,
    ProgressCallback,
    annotate_unlabelled_images,
)
from core.media.asset_tags import tag_contents


def label_generated_sprites(
    config: Any,
    files: list[str],
    *,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    if is_cancelled and is_cancelled():
        raise AnnotationCancelled("图片智能标注已取消")
    try:
        if not configured_vision_available(config.config.api_config):
            raise ValueError(
                "请在 AI 服务中配置可用的视觉模型，或关闭生成后的自动标注。"
            )
        manager = configured_vision_manager()
    except Exception as exc:
        return [""] * len(files), [
            {"index": index, "message": str(exc)} for index in range(len(files))
        ]

    def infer(image: bytes, prompt: str) -> str:
        try:
            return manager.describe(image, prompt)
        except AnnotationCancelled:
            raise
        except Exception as exc:
            # Preserve successful labels if another image's provider call fails.
            raise ValueError(str(exc)) from exc

    result = annotate_unlabelled_images(
        [{"path": file} for file in files],
        "",
        prefix="立绘",
        prompt=CHARACTER_PROMPT,
        project_root=output_dir,
        infer=infer,
        on_progress=on_progress,
        is_cancelled=is_cancelled,
    )
    return tag_contents(result["tags"], len(files)), result["failures"]

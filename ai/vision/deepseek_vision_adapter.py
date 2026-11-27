"""Compatibility facade re-exporting DeepSeek vision adapter symbols."""

from __future__ import annotations

from ai.vision.adapters.deepseek import (
    DEFAULT_DEEPSEEK_VISION_BASE_URL,
    DEFAULT_DEEPSEEK_VISION_MODEL,
    DeepSeekVisionAdapter,
    DeepseekVisionAdapter,
    DeepseekVisonAdapter,
    _image_media_type,
)

__all__ = [
    "DEFAULT_DEEPSEEK_VISION_BASE_URL",
    "DEFAULT_DEEPSEEK_VISION_MODEL",
    "DeepSeekVisionAdapter",
    "DeepseekVisionAdapter",
    "DeepseekVisonAdapter",
    "_image_media_type",
]

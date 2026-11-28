"""Compatibility facade re-exporting provider vision adapters."""

from __future__ import annotations

from ai.vision.adapters.providers import (
    ChatGPTVisionAdapter,
    ClaudeVisionAdapter,
    DoubaoVisionAdapter,
    GeminiVisionAdapter,
    OllamaVisionAdapter,
    OpenAICompatibleVisionAdapter,
    QwenVisionAdapter,
)

__all__ = [
    "ChatGPTVisionAdapter",
    "ClaudeVisionAdapter",
    "DoubaoVisionAdapter",
    "GeminiVisionAdapter",
    "OllamaVisionAdapter",
    "OpenAICompatibleVisionAdapter",
    "QwenVisionAdapter",
]

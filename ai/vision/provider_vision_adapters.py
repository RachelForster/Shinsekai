from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI

from ai.llm.claude_url import normalize_claude_base_url_for_sdk
from ai.vision.deepseek_vision_adapter import _image_media_type
from ai.vision.vision_adapter import VisionAdapter
from config.vision_defaults import (
    VISION_BASE_URLS,
    VISION_DEFAULT_MODELS,
    resolve_vision_api_key,
    vision_provider_requires_api_key,
)


def _configured_values(provider: str) -> tuple[str, str, str]:
    from config.config_manager import ConfigManager

    config = ConfigManager().config.api_config
    provider_key = provider.strip().lower()
    api_key = resolve_vision_api_key(config, provider_key)
    base_url = str(
        (config.vision_base_url or {}).get(provider_key, "")
        or VISION_BASE_URLS.get(provider_key, "")
    ).strip()
    model = str(
        (config.vision_model or {}).get(provider_key, "")
        or VISION_DEFAULT_MODELS.get(provider_key, "")
    ).strip()
    return api_key, base_url, model


def _response_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    content = getattr(getattr(choices[0], "message", None), "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    return str(content or "")


class OpenAICompatibleVisionAdapter(VisionAdapter):
    """Image understanding over an OpenAI-compatible Chat Completions API."""

    provider = ""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if api_key is None or base_url is None or model is None:
            configured_key, configured_url, configured_model = _configured_values(
                self.provider
            )
            api_key = configured_key if api_key is None else api_key
            base_url = configured_url if base_url is None else base_url
            model = configured_model if model is None else model

        self.api_key = str(api_key or "").strip()
        self.base_url = str(
            base_url or VISION_BASE_URLS.get(self.provider, "")
        ).strip()
        self.model = str(
            model or VISION_DEFAULT_MODELS.get(self.provider, "")
        ).strip()
        if vision_provider_requires_api_key(self.provider) and not self.api_key:
            raise ValueError(f"{self.provider} 视觉 API Key 不能为空。")
        if not self.base_url or not self.model:
            raise ValueError(f"{self.provider} 视觉基础 URL 和模型 ID 不能为空。")
        self.client = client or OpenAI(
            api_key=self.api_key or "ollama",
            base_url=self.base_url,
        )

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        media_type = _image_media_type(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": str(prompt or "Describe this image accurately.")},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{encoded}",
                            },
                        },
                    ],
                }
            ],
        )
        return _response_text(response)


class ChatGPTVisionAdapter(OpenAICompatibleVisionAdapter):
    provider = "chatgpt"


class GeminiVisionAdapter(OpenAICompatibleVisionAdapter):
    provider = "gemini"


class DoubaoVisionAdapter(OpenAICompatibleVisionAdapter):
    provider = "doubao"


class QwenVisionAdapter(OpenAICompatibleVisionAdapter):
    provider = "qwen"


class OllamaVisionAdapter(OpenAICompatibleVisionAdapter):
    provider = "ollama"


class ClaudeVisionAdapter(VisionAdapter):
    provider = "claude"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if api_key is None or base_url is None or model is None:
            configured_key, configured_url, configured_model = _configured_values(
                self.provider
            )
            api_key = configured_key if api_key is None else api_key
            base_url = configured_url if base_url is None else base_url
            model = configured_model if model is None else model
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or VISION_BASE_URLS[self.provider]).strip()
        self.model = str(model or VISION_DEFAULT_MODELS[self.provider]).strip()
        if not self.api_key or not self.base_url or not self.model:
            raise ValueError("Claude 视觉的基础 URL、API Key 和模型 ID 都需要填写。")
        if client is None:
            import anthropic

            client = anthropic.Anthropic(
                api_key=self.api_key,
                base_url=normalize_claude_base_url_for_sdk(self.base_url),
            )
        self.client = client

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        media_type = _image_media_type(image_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": str(prompt or "Describe this image accurately.")},
                    ],
                }
            ],
        )
        blocks = getattr(response, "content", None) or []
        return "\n".join(
            str(getattr(block, "text", "") or "")
            for block in blocks
            if getattr(block, "type", "") == "text"
        ).strip()


__all__ = [
    "ChatGPTVisionAdapter",
    "ClaudeVisionAdapter",
    "DoubaoVisionAdapter",
    "GeminiVisionAdapter",
    "OllamaVisionAdapter",
    "OpenAICompatibleVisionAdapter",
    "QwenVisionAdapter",
]

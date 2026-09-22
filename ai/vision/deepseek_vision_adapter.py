from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI

from ai.vision.vision_adapter import VisionAdapter


DEFAULT_DEEPSEEK_VISION_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_VISION_MODEL = "deepseek-flash"
_DETAIL_LEVELS = {"auto", "low", "high", "original"}


def _image_media_type(image_bytes: bytes) -> str:
    """Detect the formats accepted by DeepSeek from the actual file content."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("DeepSeek 视觉仅支持 JPEG、PNG、GIF 和 WebP 图片。")


def _configured_values() -> tuple[str, str, str, str]:
    """Load the active DeepSeek vision settings without coupling the SDK contract to config."""
    from config.config_manager import ConfigManager

    config = ConfigManager().config.api_config
    provider = "deepseek"
    api_key = str((config.vision_api_key or {}).get(provider, "") or "").strip()
    base_url = str((config.vision_base_url or {}).get(provider, "") or "").strip()
    model = str((config.vision_model or {}).get(provider, "") or "").strip()
    detail = str((config.vision_extra_configs or {}).get(provider, {}).get("detail", "auto") or "auto").strip()
    return api_key, base_url, model, detail


class DeepseekVisionAdapter(VisionAdapter):
    """DeepSeek image-understanding adapter using Chat Completions image blocks."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        detail: str | None = None,
        client: Any | None = None,
    ) -> None:
        if api_key is None or base_url is None or model is None or detail is None:
            configured_api_key, configured_base_url, configured_model, configured_detail = _configured_values()
            api_key = configured_api_key if api_key is None else api_key
            base_url = configured_base_url if base_url is None else base_url
            model = configured_model if model is None else model
            detail = configured_detail if detail is None else detail

        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or DEFAULT_DEEPSEEK_VISION_BASE_URL).strip()
        self.model = str(model or DEFAULT_DEEPSEEK_VISION_MODEL).strip()
        normalized_detail = str(detail or "auto").strip().lower()
        self.detail = normalized_detail if normalized_detail in _DETAIL_LEVELS else "auto"
        if not self.api_key:
            raise ValueError("DeepSeek 视觉 API Key 不能为空。")
        self.client = client or OpenAI(api_key=self.api_key, base_url=self.base_url)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "detail": {
                "type": "str",
                "label": "图片细节级别",
                "default": "auto",
                "choices": ["auto", "low", "high", "original"],
            }
        }

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
                                "detail": self.detail,
                            },
                        },
                    ],
                }
            ],
        )
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


# Keep the spelling used in early integrations import-compatible.
DeepSeekVisionAdapter = DeepseekVisionAdapter
DeepseekVisonAdapter = DeepseekVisionAdapter


__all__ = [
    "DEFAULT_DEEPSEEK_VISION_BASE_URL",
    "DEFAULT_DEEPSEEK_VISION_MODEL",
    "DeepSeekVisionAdapter",
    "DeepseekVisonAdapter",
    "DeepseekVisionAdapter",
]

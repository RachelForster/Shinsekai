"""Alibaba Cloud CosyVoice TTS adapter."""

from __future__ import annotations

import os
from typing import Any

import requests

from core.adapters import builtin_adapter
from sdk.adapters import TTSAdapter
from sdk.logging import get_logger

logger = get_logger(__name__)


@builtin_adapter("cosyvoice", label="CosyVoice", order=60)
class CosyVoiceAdapter(TTSAdapter):
    """Adapter for the CosyVoice (Alibaba Cloud) TTS service."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "cosyvoice-v2",
        voice: str = "longxiaochun_v2",
        **_ignored: Any,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.current_model = str(model or "cosyvoice-v2").strip() or "cosyvoice-v2"
        self.current_voice = str(voice or "longxiaochun_v2").strip() or "longxiaochun_v2"

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "api_key": {
                "label": "CosyVoice API Key",
                "default": "",
                "secret": True,
                "type": "str",
            },
            "model": {
                "label": "CosyVoice 模型",
                "type": "str",
                "default": "cosyvoice-v2",
            },
            "voice": {
                "label": "CosyVoice 音色",
                "type": "str",
                "default": "longxiaochun_v2",
            },
        }

    def generate_speech(self, text: str, file_path: str | None = None, **kwargs: Any) -> str | None:
        """Generate TTS audio using the CosyVoice HTTP API."""
        if not self.api_key:
            logger.warning("CosyVoice API key is empty.")
            return None
        api_url = "https://dashscope.aliyuncs.com/api/v1/tts/cosyvoice"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        params = {
            "model": kwargs.get("model", self.current_model),
            "voice": kwargs.get("voice", self.current_voice),
            "text": text,
        }

        try:
            response = requests.post(api_url, headers=headers, json=params)
            response.raise_for_status()

            target_path = file_path or "temp_cosyvoice.wav"
            with open(target_path, "wb") as handle:
                handle.write(response.content)

            return os.path.abspath(target_path)
        except Exception as exc:
            logger.error("CosyVoice TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        """Switch the active CosyVoice voice and model."""
        info = model_info or {}
        voice = info.get("voice")
        model = info.get("model")

        if voice:
            self.current_voice = voice
            logger.info("CosyVoice voice switched to: %s", self.current_voice)
        if model:
            self.current_model = model
            logger.info("CosyVoice model switched to: %s", self.current_model)

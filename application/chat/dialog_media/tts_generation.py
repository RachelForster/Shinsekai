"""Strategies for synthesizing or retrieving character speech audio."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urlparse

from .models import TtsGenerationRequest


class TtsGenerationStrategy(ABC):
    """Resolve the audio paths for one character dialog message."""

    @abstractmethod
    def generate(self, request: TtsGenerationRequest) -> Iterable[str]:
        """Return audio paths in playback order."""


class DefaultTtsGenerationStrategy(TtsGenerationStrategy):
    """Use configured fixed audio when available, otherwise synthesize speech."""

    def generate(self, request: TtsGenerationRequest) -> Iterator[str]:
        manager = request.runtime.tts_manager
        if manager is None:
            yield self._fallback_audio_path(request)
            return

        character = request.character
        manager.switch_model(
            {
                "character_name": request.character_name,
                "sovits_model_path": Path(character.sovits_model_path)
                .resolve()
                .as_posix(),
                "gpt_model_path": Path(character.gpt_model_path).resolve().as_posix(),
            }
        )

        sprite = request.sprite
        if sprite.voice_type == "preset" and sprite.voice_path:
            yield self._absolute(sprite.voice_path)
            return

        speech_text, text_processor = self._speech_input(request)
        ref_audio_path = self._absolute(character.refer_audio_path)
        prompt_text = character.prompt_text
        if self._can_use_sprite_reference(request):
            ref_audio_path = self._absolute(sprite.voice_path)
            prompt_text = sprite.voice_text

        if text_processor:
            speech_text = text_processor.remove_parentheses(speech_text)

        sentences = self._sentences(request, speech_text)
        if len(sentences) <= 1:
            audio_path = manager.generate_tts(
                speech_text,
                text_processor=text_processor,
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                prompt_lang=character.prompt_lang,
                character_name=request.character_name,
                speed_factor=character.speech_speed,
            )
            yield audio_path or ""
            return

        for sentence in sentences:
            audio_path = manager.generate_tts(
                sentence,
                text_processor=text_processor,
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                prompt_lang=character.prompt_lang,
                character_name=request.character_name,
                speed_factor=character.speech_speed,
            )
            if not self._is_audio_file(audio_path):
                yield ""
                return
            yield audio_path

    def _fallback_audio_path(self, request: TtsGenerationRequest) -> str:
        sprite = request.sprite
        if sprite.voice_type in {"fallback", "preset"} and sprite.voice_path:
            return self._absolute(sprite.voice_path)
        return ""

    @staticmethod
    def _speech_input(request: TtsGenerationRequest):
        speech = request.message.text or ""
        text_processor = request.runtime.text_processor
        if not request.message.translate:
            return speech, text_processor
        translated = text_processor.remove_parentheses(request.message.translate)
        return text_processor.replace_names(translated), None

    @staticmethod
    def _sentences(request: TtsGenerationRequest, speech_text: str) -> list[str]:
        api_config = request.runtime.config.config.api_config
        if not getattr(api_config, "tts_split_enabled", False):
            return []
        max_length = getattr(api_config, "tts_max_sentence_length", 15)
        pieces = re.split(r"(?<=[。！？，、；：\.!\?,;:])", speech_text)
        pieces = [piece.strip() for piece in pieces if piece.strip()]
        sentences: list[str] = []
        current = ""
        for piece in pieces:
            if not current:
                current = piece
            elif len(current) + len(piece) <= max_length:
                current += piece
            else:
                sentences.append(current)
                current = piece
        if current:
            sentences.append(current)
        return sentences

    @staticmethod
    def _can_use_sprite_reference(request: TtsGenerationRequest) -> bool:
        sprite = request.sprite
        if not sprite.voice_path or not sprite.voice_text:
            return False
        if sprite.voice_type not in {None, "reference"}:
            return False
        if not DefaultTtsGenerationStrategy._is_remote_gpt_sovits(request):
            return True
        return sprite.voice_path.strip().startswith("/kaggle/")

    @staticmethod
    def _is_remote_gpt_sovits(request: TtsGenerationRequest) -> bool:
        api_config = request.runtime.config.config.api_config
        provider = str(getattr(api_config, "tts_provider", "") or "").strip().lower()
        host = (
            urlparse(str(getattr(api_config, "gpt_sovits_url", "") or "")).hostname
            or ""
        ).lower()
        return provider == "kaggle-gpt-sovits" or (
            provider == "gpt-sovits"
            and host not in {"", "127.0.0.1", "localhost", "0.0.0.0", "::1"}
        )

    @staticmethod
    def _absolute(path: str | Path | None) -> str:
        return Path(path or "").resolve().as_posix()

    @staticmethod
    def _is_audio_file(path: str | None) -> bool:
        return bool(path and Path(path).is_file() and Path(path).stat().st_size > 0)

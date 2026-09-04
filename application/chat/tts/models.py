"""Values exchanged by the sprite lookup and TTS generation strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sdk.messages import LLMDialogMessage


@dataclass(frozen=True, slots=True)
class SpriteLookupRequest:
    """Everything a strategy may use to choose a character sprite."""

    character: Any
    message: LLMDialogMessage


@dataclass(frozen=True, slots=True)
class SpriteMatch:
    """A selected sprite and the voice metadata attached to it."""

    asset_id: str
    index: int | None = None
    sprite: Any | None = None
    voice_type: str | None = None
    voice_path: str = ""
    voice_text: str = ""

    @property
    def found(self) -> bool:
        return self.index is not None and self.sprite is not None


@dataclass(frozen=True, slots=True)
class TtsGenerationRequest:
    """Inputs needed to synthesize or retrieve audio for one dialog message."""

    runtime: Any
    character: Any
    character_name: str
    message: LLMDialogMessage
    sprite: SpriteMatch

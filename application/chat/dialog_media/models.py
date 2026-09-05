"""Values exchanged while preparing character speech."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sdk.messages import LLMDialogMessage
from .resolver import ResolvedSpriteAsset


@dataclass(frozen=True, slots=True)
class TtsGenerationRequest:
    """Inputs needed to synthesize or retrieve audio for one dialog message."""

    runtime: Any
    character: Any
    character_name: str
    message: LLMDialogMessage
    sprite: ResolvedSpriteAsset

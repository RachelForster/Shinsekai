"""An image or ambient effect and its optional bound audio resolved as one asset."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageEffectAsset:
    """One-shot screen image effect with optional paired sound."""

    image_path: str
    audio_path: str = ""


@dataclass(frozen=True)
class AmbientEffectAsset:
    """A persistent full-screen effect with an optional looping soundtrack."""

    path: str
    audio_path: str = ""
    layer: str = "back"


__all__ = ["AmbientEffectAsset", "ImageEffectAsset"]

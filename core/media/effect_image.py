"""An image effect and its optional audio are resolved as one resource."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageEffectAsset:
    image_path: str
    audio_path: str = ""

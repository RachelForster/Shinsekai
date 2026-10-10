from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Dict, Optional


class T2IAdapter(ABC):
    """Public image generation/editing interface.

    Base defaults and conventions:
        - ``get_config_schema()``: Returns ``{}`` by default; non-empty schema follows
          ``LLMAdapter.get_config_schema`` meta keys.
        - ``reference_images``: Ordered local image paths; ``None``/``[]`` means text-to-image.
          Backends that cannot edit images must reject non-empty references rather than ignore them.
        - ``generate_image(prompt, file_path=None, **kwargs)``: Abstract signature defaults ``file_path``
          to ``None``. Constructor settings for ComfyUI-style backends (``api_url``, ``workflow_path``,
          node IDs, etc.) are passed by subclasses / factories; defaults live in ``ApiConfig``.
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        """Metadata for adapter-specific options; empty ``{}`` means none."""
        return {}

    @abstractmethod
    def generate_image(
        self,
        prompt: str,
        file_path: Optional[str] = None,
        *,
        reference_images: Sequence[str | Path] | None = None,
        **kwargs,
    ) -> Optional[str]:
        pass

    @staticmethod
    def normalize_reference_images(
        images: Sequence[str | Path] | None,
    ) -> tuple[str, ...]:
        """Snapshot ordered references so queued requests cannot be changed by their caller."""
        if images is None:
            return ()
        if isinstance(images, (str, bytes)) or not isinstance(images, Sequence):
            raise ValueError("reference_images must be an array of local image paths")
        if any(
            not isinstance(path, (str, Path)) or not str(path).strip()
            for path in images
        ):
            raise ValueError(
                "reference_images must contain non-empty local image paths"
            )
        return tuple(str(path) for path in images)

    def shutdown(self) -> None:
        """Release backend resources; adapters without owned resources need no cleanup."""

    @abstractmethod
    def switch_model(self, model_info: Dict[str, Any]) -> None:
        pass

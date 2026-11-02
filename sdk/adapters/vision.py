from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


class VisionAdapter(ABC):
    """Provider-neutral interface for understanding a single image."""

    @abstractmethod
    def describe(self, image_bytes: bytes, prompt: str) -> str:
        """Return a textual answer for ``prompt`` about ``image_bytes``."""


VisionAdapterFactory = Callable[[], VisionAdapter]
VisionAvailabilityProbe = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class VisionFallbackContribution:
    """A plugin-provided image-understanding backend used by text-only LLMs.

    Lower ``priority`` values are preferred. The host tries the next available
    contribution when a probe returns ``False`` or raises.
    """

    provider: str
    factory: VisionAdapterFactory
    available: VisionAvailabilityProbe
    priority: int = 100

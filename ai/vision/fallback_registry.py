"""Host-configured vision fallbacks consumed by :mod:`ai.vision.service`.

Plugins register these capabilities through :mod:`sdk`; this module only owns
the runtime snapshot selected by the plugin host.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

from sdk.adapters import VisionFallbackContribution

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_registered: tuple[VisionFallbackContribution, ...] = ()


def configure_registered_fallbacks(
    contributions: Iterable[VisionFallbackContribution],
) -> None:
    """Atomically replace the host's ordered vision-fallback snapshot."""
    ordered = tuple(
        sorted(
            contributions,
            key=lambda contribution: (contribution.priority, contribution.provider),
        )
    )
    with _lock:
        global _registered
        _registered = ordered


def active_vision_fallback() -> VisionFallbackContribution | None:
    """Return the highest-priority fallback whose availability probe succeeds."""
    with _lock:
        registered = _registered
    for contribution in registered:
        try:
            if contribution.available():
                return contribution
        except Exception:
            logger.debug(
                "vision fallback %r availability probe failed",
                contribution.provider,
                exc_info=True,
            )
    return None

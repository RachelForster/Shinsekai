"""Optional plugin-provided override for the chat image-understanding fallback.

When the active language model lacks native vision, :class:`ai.vision.service.ChatVisionService`
describes image attachments with a fallback vision model.  The built-in default
is the local Moondream plugin.  A plugin may register a *preferred* fallback
here (for example a cloud vision API) to take priority over Moondream while it
is available.

The slot is intentionally generic: it stores opaque callables and never imports
provider code, so any plugin can drive it without coupling the core to a
specific implementation.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ``factory`` returns an object exposing ``describe(image_bytes, prompt) -> str``
# (i.e. a :class:`~ai.vision.vision_manager.VisionManager`).
VisionManagerFactory = Callable[[], Any]
AvailabilityProbe = Callable[[], bool]


@dataclass(frozen=True)
class PreferredVisionFallback:
    label: str
    factory: VisionManagerFactory
    available: AvailabilityProbe


_lock = threading.RLock()
_preferred: PreferredVisionFallback | None = None


def set_preferred_fallback(
    label: str,
    factory: VisionManagerFactory,
    available: AvailabilityProbe,
) -> None:
    """Register (or replace) the preferred vision fallback.

    ``factory`` returns an object with ``describe(image_bytes, prompt) -> str``.
    ``available`` reports whether the fallback can currently run; when it returns
    ``False`` (or raises) callers transparently fall back to the built-in
    default.  Registering with an existing ``label`` replaces that entry.
    """

    global _preferred
    clean = str(label or "").strip()
    if not clean:
        raise ValueError("preferred vision fallback label cannot be empty")
    if not callable(factory) or not callable(available):
        raise TypeError("factory and available must be callables")
    with _lock:
        _preferred = PreferredVisionFallback(clean, factory, available)


def clear_preferred_fallback(label: str | None = None) -> None:
    """Remove the preferred fallback.

    When *label* is provided, the entry is cleared only if the current
    registration matches it, so a plugin never clears another plugin's entry.
    """

    global _preferred
    clean = None if label is None else str(label).strip()
    with _lock:
        if _preferred is None:
            return
        if clean is not None and _preferred.label != clean:
            return
        _preferred = None


def active_preferred_fallback() -> PreferredVisionFallback | None:
    """Return the preferred fallback if one is registered and currently available."""

    with _lock:
        pref = _preferred
    if pref is None:
        return None
    try:
        if not pref.available():
            return None
    except Exception:
        logger.debug(
            "preferred vision fallback %r availability probe failed",
            pref.label,
            exc_info=True,
        )
        return None
    return pref

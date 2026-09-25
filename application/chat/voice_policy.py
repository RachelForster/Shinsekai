"""Voice policy helpers for chat sessions."""

from __future__ import annotations

from typing import Any


def character_speech_disabled(config: Any) -> bool:
    """Return whether character speech is disabled for the session.

    Takes an existing ConfigManager-like object with `.config.system_config`.
    Safely returns False when config or system_config is absent.
    """
    system_config = getattr(getattr(config, "config", None), "system_config", None)
    if system_config is None:
        system_config = getattr(config, "system_config", None)
    return bool(
        getattr(
            system_config,
            "asr_continuous_during_reply_experimental_enabled",
            False,
        )
    )

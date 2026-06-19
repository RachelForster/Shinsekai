from __future__ import annotations


def should_init_desktop_mixer(*, headless: bool, stream_endpoint: str) -> bool:
    """Return whether main.py should initialize the shared desktop mixer upfront."""

    return not headless and not str(stream_endpoint or "").strip()

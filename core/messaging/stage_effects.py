"""Canonical scene transition and character motion stage effects."""

from __future__ import annotations

import re

SCENE_TRANSITIONS: frozenset[str] = frozenset(
    {
        "fade",
        "fade_black",
        "fade_white",
        "slide_left",
        "slide_right",
        "zoom",
        "cut",
    }
)

SCENE_TRANSITION_ALIASES: dict[str, str] = {
    "crossfade": "fade",
    "dissolve": "fade",
    "black": "fade_black",
    "dip_black": "fade_black",
    "fadeblack": "fade_black",
    "white": "fade_white",
    "dip_white": "fade_white",
    "fadewhite": "fade_white",
    "slideleft": "slide_left",
    "left": "slide_left",
    "slideright": "slide_right",
    "right": "slide_right",
    "zoom_in": "zoom",
    "push": "zoom",
    "none": "cut",
    "instant": "cut",
    "hard": "cut",
}

SCENE_TRANSITION_DURATIONS_MS: dict[str, int] = {
    "fade": 480,
    "fade_black": 680,
    "fade_white": 680,
    "slide_left": 520,
    "slide_right": 520,
    "zoom": 560,
    "cut": 0,
}

CHARACTER_MOTIONS: frozenset[str] = frozenset(
    {
        "shake",
        "tremble",
        "jump",
        "bounce",
        "nod",
        "tilt",
        "flash",
        "sink",
        "lean_in",
    }
)

CHARACTER_MOTION_ALIASES: dict[str, str] = {
    "flinch": "shake",
    "shiver": "tremble",
    "quiver": "tremble",
    "shudder": "tremble",
    "hop": "jump",
    "startle": "jump",
    "leanin": "lean_in",
    "approach": "lean_in",
    "droop": "sink",
    "slump": "sink",
    "blink": "flash",
}

CHARACTER_MOTION_DURATIONS_MS: dict[str, int] = {
    "shake": 460,
    "tremble": 700,
    "jump": 480,
    "bounce": 560,
    "nod": 460,
    "tilt": 560,
    "flash": 420,
    "sink": 620,
    "lean_in": 520,
}


def _normalize_token(raw: object) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[-\s]+", "_", text)


def normalize_scene_transition(raw: object) -> str:
    """Return canonical scene transition name or empty string if unrecognized."""
    token = _normalize_token(raw)
    if not token:
        return ""
    token = SCENE_TRANSITION_ALIASES.get(token, token)
    return token if token in SCENE_TRANSITIONS else ""


def normalize_character_motion(raw: object) -> str:
    """Return canonical character motion name or empty string if unrecognized."""
    token = _normalize_token(raw)
    if not token:
        return ""
    token = CHARACTER_MOTION_ALIASES.get(token, token)
    return token if token in CHARACTER_MOTIONS else ""


def scene_transition_duration_ms(transition: str) -> int:
    """Return CSS animation duration in milliseconds for a normalized transition."""
    normalized = normalize_scene_transition(transition)
    return SCENE_TRANSITION_DURATIONS_MS.get(normalized, 0)


def character_motion_duration_ms(motion: str) -> int:
    """Return CSS animation duration in milliseconds for a normalized character motion."""
    normalized = normalize_character_motion(motion)
    return CHARACTER_MOTION_DURATIONS_MS.get(normalized, 500)

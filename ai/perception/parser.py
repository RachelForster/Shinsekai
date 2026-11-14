"""Streaming and resilient JSON/text parsers for local perception outputs."""

from __future__ import annotations

import json
import re
from typing import Any

from core.perception.models import (
    PerceptionDigestResult,
    ReflexDecision,
    normalize_scene_mood,
    normalize_visual_change,
)

_REFLEX_OBJECT_RE = re.compile(r'"reflex"\s*:\s*(\{[^{}]*\})', re.DOTALL)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_STYLE_PREFIX_RE = re.compile(r"^(?:说话风格|说话口吻|口吻|语气|风格)[：:\s]*")
_SUMMARY_PREFIX_RE = re.compile(r"^(?:分段纪要|前情纪要|摘要|总结)[：:\s]*")

DEFAULT_VOICE_STYLE = "自然简短"


class InvalidPerceptionDecision(ValueError):
    """The model replied without a recognizable scene decision."""


def sanitize_voice_style(raw_text: str, *, character_name: str = "") -> str:
    """Clean model-extracted speaking style, stripping character name and noisy wrappers."""
    cleaned = _CODE_FENCE_RE.sub("", str(raw_text or "").strip())
    cleaned = cleaned.splitlines()[0].strip() if cleaned else ""
    cleaned = _STYLE_PREFIX_RE.sub("", cleaned).strip(" \"'“”‘’。！!；;，,")
    if character_name:
        cleaned = cleaned.replace(character_name.strip(), "").strip(" 、，,")
    if not cleaned or len(cleaned) > 30 or "{" in cleaned or "}" in cleaned:
        return DEFAULT_VOICE_STYLE
    return cleaned


def sanitize_episode_summary(raw_text: str) -> str:
    cleaned = _CODE_FENCE_RE.sub("", str(raw_text or "").strip())
    cleaned = " ".join(line.strip() for line in cleaned.splitlines() if line.strip())
    cleaned = _SUMMARY_PREFIX_RE.sub("", cleaned).strip()
    return cleaned[:200]


def try_extract_early_reflex(partial_text: str) -> ReflexDecision | None:
    """Extract `ReflexDecision` as soon as the `"reflex":{...}` object closes."""
    if not partial_text:
        return None
    match = _REFLEX_OBJECT_RE.search(partial_text)
    if match is None:
        return None
    try:
        raw_obj = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_obj, dict):
        return None
    return ReflexDecision.from_mapping(raw_obj)


def parse_perception_decision_json(
    raw_text: str,
    *,
    game: str = "",
    latency_ms: float = 0.0,
) -> PerceptionDigestResult:
    """Parse complete model JSON output with resilient regex fallback."""
    cleaned = _CODE_FENCE_RE.sub("", str(raw_text or "").strip()).strip()
    if not cleaned:
        raise InvalidPerceptionDecision("Visual model returned an empty response")

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    candidate = cleaned[start : end + 1] if (start != -1 and end > start) else cleaned

    parsed: dict[str, Any] | None = None
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            parsed = obj
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        early = try_extract_early_reflex(cleaned) or ReflexDecision()
        mood_match = re.search(r'"mood"\s*:\s*"([^"]*)"', cleaned)
        change_match = re.search(r'"visual_change"\s*:\s*"([^"]*)"', cleaned)
        salience_match = re.search(r'"salience"\s*:\s*([0-9]*\.?[0-9]+)', cleaned)
        busy_match = re.search(r'"player_busy"\s*:\s*(true|false)', cleaned, re.IGNORECASE)
        digest_match = re.search(r'"digest"\s*:\s*"([^"]*)"', cleaned)
        salience_val = float(salience_match.group(1)) if salience_match else 0.0
        busy_val = busy_match.group(1).lower() == "true" if busy_match else False
        digest_val = digest_match.group(1).strip() if digest_match else ""
        raw_change = change_match.group(1).strip() if change_match else ""
        visual_change = (
            normalize_visual_change(raw_change, has_digest=bool(digest_val))
            if raw_change
            else ""
        )
        if not digest_val and not early.act and raw_change.casefold() != "none":
            raise InvalidPerceptionDecision("Visual model returned no readable scene decision")
        return PerceptionDigestResult(
            reflex=early,
            salience=max(0.0, min(1.0, salience_val)),
            player_busy=busy_val,
            digest=digest_val[:160],
            game=game,
            latency_ms=latency_ms,
            mood=normalize_scene_mood(mood_match.group(1) if mood_match else ""),
            visual_change=visual_change,
        )

    raw_reflex = parsed.get("reflex")
    reflex = ReflexDecision.from_mapping(raw_reflex)
    fields = {**raw_reflex, **parsed} if isinstance(raw_reflex, dict) else parsed
    try:
        salience = max(0.0, min(1.0, float(fields.get("salience", 0.0) or 0.0)))
    except (TypeError, ValueError):
        salience = 0.0
    player_busy = bool(fields.get("player_busy", False))
    digest = str(fields.get("digest") or "").strip()[:160]
    mood = normalize_scene_mood(fields.get("mood"))
    explicit_change = fields.get("visual_change")
    visual_change = (
        normalize_visual_change(explicit_change, has_digest=bool(digest))
        if explicit_change is not None and str(explicit_change).strip()
        else ""
    )

    if not digest and not reflex.act:
        explicit_none_change = isinstance(explicit_change, str) and explicit_change.strip().casefold() in {
            "none",
            "same",
            "unchanged",
            "static",
        }
        quiet = explicit_none_change or ("reflex" in parsed and raw_reflex is None)
        if isinstance(raw_reflex, dict):
            quiet = quiet or (
                raw_reflex.get("act") is False
                or ("sprite_id" in raw_reflex and raw_reflex["sprite_id"] is None)
            )
        if not quiet or (not explicit_none_change and not isinstance(fields.get("digest"), str)):
            raise InvalidPerceptionDecision("Visual model returned no readable scene decision")
        if not (explicit_none_change and salience >= 0.5):
            salience = 0.0

    return PerceptionDigestResult(
        reflex=reflex,
        salience=salience,
        player_busy=player_busy,
        digest=digest,
        game=game,
        latency_ms=latency_ms,
        mood=mood,
        visual_change=visual_change,
    )

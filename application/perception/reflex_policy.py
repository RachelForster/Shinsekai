"""Fast-path reflex policy: sprite rotation, cooldowns, mood gating, and ambient bubbles."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import replace
from difflib import SequenceMatcher
import re

from application.perception.expressions import canonical_expression
from core.perception.cache import is_ambient_reaction_bark
from core.perception.models import PerceptionConfig, PerceptionDigestResult, ReflexDecision

_LEADING_INTERJECTIONS = "哇咦诶哎欸啊哦嗯唔"
_LEADING_SCENE_PREFIX_RE = re.compile(
    r"^(?:当前|右侧|右边)?(?:的)?(?:画面|镜头|场景)(?:中|里)?(?:显示|看见|为|是|切换到|转到)?[：:\s]*"
)
_AMBIENT_WRAPPER_RE = re.compile(r"^[（(](?:正在读[：:\s]*|看着)(.*?)(?:……|…|\.{2,})?[）)]$")


def comparison_text(value: str) -> str:
    raw = str(value or "").strip()
    ambient_match = _AMBIENT_WRAPPER_RE.match(raw)
    if ambient_match is not None:
        raw = ambient_match.group(1)
    return "".join(char.casefold() for char in raw if char.isalnum())


def similar_bark(left: str, right: str) -> bool:
    if left == right:
        return True
    left_body = left.lstrip(_LEADING_INTERJECTIONS)
    right_body = right.lstrip(_LEADING_INTERJECTIONS)
    return (
        min(len(left_body), len(right_body)) >= 6
        and SequenceMatcher(None, left_body, right_body).ratio() >= 0.82
    )


def short_visual_focus(digest: str) -> str:
    cleaned = _LEADING_SCENE_PREFIX_RE.sub("", str(digest or "").strip())
    clause = re.split(r"[，,。；;！？!?\n]", cleaned, maxsplit=1)[0].strip()
    return clause[:14].rstrip() if len(clause) >= 2 else ""


def short_reading_focus(screen_text: str) -> str:
    first_line = next(
        (line.strip() for line in str(screen_text or "").splitlines() if line.strip()),
        "",
    )
    cleaned = first_line.strip(" \"'“”‘’「」『』").rstrip("。，,；;：:")
    if len(cleaned) < 2:
        return ""
    if len(cleaned) > 16:
        return cleaned[:15].rstrip() + "…"
    return cleaned


class ReflexPolicy:
    """Stateful cooldown, deduplication, sprite-rotation, and Option B ambient bubble policy."""

    def __init__(self) -> None:
        self.last_bark_monotonic: float = 0.0
        self.recent_barks: deque[tuple[float, str, str]] = deque(maxlen=8)
        self.last_sprite: tuple[str, int] | None = None
        self.last_sprite_monotonic: float = 0.0
        self.last_expression_sprite: dict[tuple[str, str], int] = {}

    def reset(self) -> None:
        self.recent_barks.clear()
        self.last_bark_monotonic = 0.0
        self.last_sprite = None
        self.last_sprite_monotonic = 0.0
        self.last_expression_sprite.clear()

    def recent_spoken_barks(
        self,
        character_name: str,
        *,
        now: float,
        max_age_sec: float = 35.0,
        limit: int = 2,
    ) -> list[str]:
        """Return recent non-ambient barks so the VLM prompt can naturally vary phrasing."""
        items = [
            text
            for shown_at, speaker, text in self.recent_barks
            if speaker == character_name
            and (now - shown_at) < max_age_sec
            and not is_ambient_reaction_bark(text)
        ]
        return items[-max(1, int(limit)) :]

    def is_bark_cooldown_open(self, *, now: float, cooldown_sec: float) -> bool:
        return self.last_bark_monotonic == 0.0 or (now - self.last_bark_monotonic) >= cooldown_sec

    def refine_for_context(
        self,
        result: PerceptionDigestResult,
        *,
        live_screen: bool,
        screen_text: str,
        screen_text_changed: bool,
        config: PerceptionConfig,
        now: float,
    ) -> ReflexDecision:
        """Apply subtitle-echo check, `unclear` mood silence, and Option B ambient bubbles."""
        reflex = result.reflex

        if live_screen and reflex.bark:
            spoken = comparison_text(reflex.bark)
            subtitle_lines = [*screen_text.splitlines(), *result.ocr_text.splitlines()]
            if len(spoken) >= 4 and any(spoken == comparison_text(line) for line in subtitle_lines):
                reflex = replace(reflex, bark="")

        if result.mood == "unclear" and reflex.bark:
            reflex = replace(reflex, bark="")

        if (
            live_screen
            and config.reflex_enabled
            and not reflex.bark
            and self.is_bark_cooldown_open(now=now, cooldown_sec=config.reflex_cooldown_sec)
        ):
            fresh_text = screen_text if screen_text_changed else (result.ocr_text or result.screen_text)
            reading_focus = short_reading_focus(fresh_text)
            if result.mood == "sad" and (
                result.salience >= 0.45 or screen_text_changed or reflex.act
            ):
                reflex = replace(reflex, act=True, bark="……")
            elif reading_focus:
                reflex = replace(reflex, act=True, bark=f"（正在读：{reading_focus}）")
            elif result.mood == "serious" and (result.salience >= 0.45 or reflex.act):
                reflex = replace(reflex, act=True, bark="……")
            elif result.visual_change == "cut" and result.digest:
                focus = short_visual_focus(result.digest)
                if focus:
                    reflex = replace(reflex, act=True, bark=f"（看着{focus}……）")

        return reflex

    def select_emission(
        self,
        reflex: ReflexDecision,
        *,
        character_name: str,
        expressions: Mapping[str, tuple[int, ...]],
        sprite_count: int,
        config: PerceptionConfig,
        sprite_choices: Mapping[int, str] | None = None,
        now: float,
    ) -> ReflexDecision | None:
        """Resolve final `(sprite, bark)` under cooldown and similarity deduplication."""
        expression = canonical_expression(reflex.expression)
        candidates = expressions.get(expression, ())
        sprite_idx = reflex.sprite
        if reflex.sprite_id is not None:
            candidates = ()
            sprite_idx = (
                reflex.sprite_id - 1
                if sprite_choices and reflex.sprite_id in sprite_choices
                else None
            )

        expression_key = (character_name, expression)
        if candidates:
            last = self.last_expression_sprite.get(expression_key)
            start = (candidates.index(last) + 1) % len(candidates) if last in candidates else 0
            ordered = (*candidates[start:], *candidates[:start])
            sprite_idx = next(
                (index for index in ordered if self.last_sprite != (character_name, index)),
                ordered[0],
            )
        if sprite_idx is not None and not 0 <= sprite_idx < sprite_count:
            sprite_idx = None

        bark = reflex.bark
        if not self.is_bark_cooldown_open(now=now, cooldown_sec=config.reflex_cooldown_sec):
            bark = ""

        bark_key = comparison_text(bark)
        if bark == "……" and any(
            character_name == speaker and (now - shown_at) < 30.0 and text == "……"
            for shown_at, speaker, text in self.recent_barks
        ):
            bark = ""
        elif bark_key and any(
            character_name == speaker
            and (now - shown_at) < 45.0
            and similar_bark(bark_key, comparison_text(text))
            for shown_at, speaker, text in self.recent_barks
        ):
            bark = ""

        if self.last_sprite == (character_name, sprite_idx) and (now - self.last_sprite_monotonic) < 4.0:
            sprite_idx = None

        if not bark and sprite_idx is None:
            return None

        if bark:
            self.last_bark_monotonic = now
            self.recent_barks.append((now, character_name, bark))
        if sprite_idx is not None:
            self.last_sprite = (character_name, sprite_idx)
            self.last_sprite_monotonic = now
            if candidates:
                self.last_expression_sprite[expression_key] = sprite_idx

        return replace(reflex, sprite=sprite_idx, bark=bark)

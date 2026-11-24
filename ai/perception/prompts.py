"""Prompt construction for multimodal perception decisions and lightweight text tasks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai.llm.template.perception import (
    PerceptionDecisionPromptContext,
    format_compact_events_json,
    format_compact_states_json,
    render_perception_decision_prompts,
    render_voice_style_messages,
)
from ai.perception.parser import (
    DEFAULT_VOICE_STYLE,
    InvalidPerceptionDecision,
    parse_perception_decision_json,
    sanitize_episode_summary,
    sanitize_voice_style,
    try_extract_early_reflex,
)
from core.perception.models import RawPerceptionSnapshot


def build_voice_style_messages(
    character_name: str,
    character_brief: str,
    *,
    locale: str | None = None,
) -> list[dict[str, str]]:
    """Build a one-off pure-text prompt extracting lore-free speaking style from `character_brief`."""
    return render_voice_style_messages(
        character_name,
        character_brief,
        locale=locale,
    )


def build_perception_messages(
    snapshot: RawPerceptionSnapshot,
    *,
    previous_digest: str,
    character_name: str = "",
    character_brief: str = "",
    voice_style: str = "",
    scene_anchor: str = "",
    recent_subtitles: Sequence[str] = (),
    recent_barks: Sequence[str] = (),
    sprite_choices: Mapping[int, str] | None = None,
    reaction_guidance: str = "",
    reflex_enabled: bool = True,
    compared_frames: bool = False,
    screen_text: str = "",
    previous_screen_text: str = "",
    screen_text_changed: bool | None = None,
    limited_ocr: bool = False,
    locale: str | None = None,
) -> list[dict[str, Any]]:
    """Construct OpenAI-compatible multimodal chat messages for `Qwen3-VL-2B-Instruct`."""
    shared_screen = (
        snapshot.frame is not None and snapshot.frame.source == "screen_share"
    )
    watching_screen = shared_screen and not (
        snapshot.primary_game or snapshot.states or snapshot.events
    )
    context = PerceptionDecisionPromptContext(
        locale=locale or "zh_CN",  # type: ignore[arg-type]
        shared_screen=shared_screen,
        watching_screen=watching_screen,
        has_frame=snapshot.frame is not None,
        previous_digest=previous_digest,
        character_name=character_name,
        character_brief=character_brief,
        voice_style=voice_style,
        scene_anchor=scene_anchor,
        recent_subtitles=tuple(recent_subtitles),
        recent_barks=tuple(recent_barks),
        sprite_choices=dict(sprite_choices or {}),
        reaction_guidance=reaction_guidance,
        reflex_enabled=reflex_enabled,
        compared_frames=compared_frames,
        screen_text=screen_text,
        previous_screen_text=previous_screen_text,
        screen_text_changed=screen_text_changed,
        limited_ocr=limited_ocr,
        compact_states_json=format_compact_states_json(snapshot.states),
        compact_events_json=format_compact_events_json(snapshot.events),
    )
    system_text, user_text = render_perception_decision_prompts(context)

    if snapshot.frame is not None:
        user_content: Any = [
            {
                "type": "image_url",
                "image_url": {"url": snapshot.frame.to_data_url()},
            },
            {"type": "text", "text": user_text},
        ]
    else:
        user_content = user_text

    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_content},
    ]


__all__ = [
    "DEFAULT_VOICE_STYLE",
    "InvalidPerceptionDecision",
    "build_perception_messages",
    "build_voice_style_messages",
    "parse_perception_decision_json",
    "sanitize_episode_summary",
    "sanitize_voice_style",
    "try_extract_early_reflex",
]

"""Perception prompt sections: local VLM decision, voice style, cloud summary, and RP context."""

from __future__ import annotations

from .cloud_summary import (
    CLOUD_SUMMARY_SPEC,
    CloudSummaryPromptContext,
    build_cloud_summary_system_section,
    build_cloud_summary_user_section,
    render_cloud_summary_messages,
)
from .decision import (
    PERCEPTION_DECISION_SPEC,
    PerceptionDecisionPromptContext,
    build_perception_decision_system_section,
    build_perception_decision_user_section,
    format_compact_events_json,
    format_compact_states_json,
    render_focus_guidance_hint,
    render_perception_decision_prompts,
)
from .rp_context import (
    PERCEPTION_CONTEXT_SENTINEL,
    RP_PERCEPTION_CONTEXT_SPEC,
    RpPerceptionContext,
    build_perception_translator,
    build_rp_perception_section,
    render_perception_turn_reply_suffix,
    render_proactive_collapsed_history,
    render_proactive_turn_instruction,
)
from .voice_style import (
    VOICE_STYLE_SPEC,
    VoiceStylePromptContext,
    build_voice_style_system_section,
    build_voice_style_user_section,
    render_voice_style_messages,
)

__all__ = [
    "CLOUD_SUMMARY_SPEC",
    "CloudSummaryPromptContext",
    "PERCEPTION_CONTEXT_SENTINEL",
    "PERCEPTION_DECISION_SPEC",
    "PerceptionDecisionPromptContext",
    "RP_PERCEPTION_CONTEXT_SPEC",
    "RpPerceptionContext",
    "VOICE_STYLE_SPEC",
    "VoiceStylePromptContext",
    "build_cloud_summary_system_section",
    "build_cloud_summary_user_section",
    "build_perception_decision_system_section",
    "build_perception_decision_user_section",
    "build_perception_translator",
    "build_rp_perception_section",
    "build_voice_style_system_section",
    "build_voice_style_user_section",
    "format_compact_events_json",
    "format_compact_states_json",
    "render_cloud_summary_messages",
    "render_focus_guidance_hint",
    "render_perception_decision_prompts",
    "render_perception_turn_reply_suffix",
    "render_proactive_collapsed_history",
    "render_proactive_turn_instruction",
    "render_voice_style_messages",
]

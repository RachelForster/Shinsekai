"""Pure Composite prompt sections for multimodal local VLM perception decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import re
from typing import Any

from sdk.lang import normalize_lang

from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection


@dataclass(frozen=True)
class PerceptionDecisionPromptContext(TemplateContext):
    """Pure data projection for local VLM perception prompt rendering."""

    shared_screen: bool = False
    watching_screen: bool = False
    has_frame: bool = False
    previous_digest: str = ""
    character_name: str = ""
    character_brief: str = ""
    voice_style: str = ""
    scene_anchor: str = ""
    recent_subtitles: tuple[str, ...] = ()
    recent_barks: tuple[str, ...] = ()
    sprite_choices: Mapping[int, str] = field(default_factory=dict)
    reaction_guidance: str = ""
    reflex_enabled: bool = True
    compared_frames: bool = False
    screen_text: str = ""
    previous_screen_text: str = ""
    screen_text_changed: bool | None = None
    limited_ocr: bool = False
    compact_states_json: str = ""
    compact_events_json: str = ""


class _PersonaSection(Section[PerceptionDecisionPromptContext]):
    def _render_self(self, context: PerceptionDecisionPromptContext) -> str:
        if context.shared_screen:
            voice = (
                str(context.voice_style or "").strip()
                or context.tr("perception.voice_style_default")
            )
            return context.tr("perception.decision_persona_screen_viewer", voice=voice)
        default_name = context.tr("perception.decision_default_character_name")
        clean_name = str(context.character_name or "").strip() or default_name
        brief = re.sub(r"\s+", " ", str(context.character_brief or "").strip())
        if len(brief) > 140:
            brief = brief[:139].rstrip() + "…"
        character_desc = (
            context.tr(
                "perception.decision_character_with_brief",
                name=clean_name,
                brief=brief,
            )
            if brief
            else clean_name
        )
        return context.tr(
            "perception.decision_persona_game_agent",
            character_desc=character_desc,
        )


class _SceneRuleSection(Section[PerceptionDecisionPromptContext]):
    def _resolve_children(
        self,
        context: PerceptionDecisionPromptContext,
    ) -> tuple[Section[PerceptionDecisionPromptContext], ...]:
        if context.watching_screen:
            return (
                I18nSection(
                    "watching_intro",
                    priority=10,
                    key="perception.decision_watching_screen_intro",
                ),
                I18nSection(
                    "mood_and_scene",
                    priority=20,
                    key="perception.decision_mood_and_scene_rule",
                ),
                I18nSection(
                    "watching_salience",
                    priority=30,
                    key="perception.decision_watching_screen_salience",
                ),
            )
        return (
            I18nSection(
                "mood_and_scene",
                priority=10,
                key="perception.decision_mood_and_scene_rule",
            ),
            I18nSection(
                "game_salience",
                priority=20,
                key="perception.decision_game_salience",
            ),
        )


class _SpriteRuleSection(Section[PerceptionDecisionPromptContext]):
    def _render_self(self, context: PerceptionDecisionPromptContext) -> str:
        if not context.sprite_choices:
            return context.tr("perception.decision_sprite_none")
        sep = "; " if context.locale == "en" else "；"
        choices = sep.join(
            f"{index} {label}" for index, label in context.sprite_choices.items()
        )
        return context.tr("perception.decision_sprite_choices", choices=choices)


class _ReflexRuleSection(Section[PerceptionDecisionPromptContext]):
    def _resolve_children(
        self,
        context: PerceptionDecisionPromptContext,
    ) -> tuple[Section[PerceptionDecisionPromptContext], ...]:
        if not context.reflex_enabled:
            return (
                I18nSection(
                    "reflex_disabled",
                    priority=10,
                    key="perception.decision_reflex_disabled",
                ),
            )
        reaction_key = (
            "perception.decision_reaction_watching_screen"
            if context.watching_screen
            else "perception.decision_reaction_game"
        )
        return (
            I18nSection("reaction_rule", priority=10, key=reaction_key),
            TextSection(
                "reaction_guidance",
                priority=20,
                text=lambda ctx: str(ctx.reaction_guidance or ""),
            ),
            _SpriteRuleSection("sprite_rule", priority=30),
            I18nSection(
                "reflex_tail",
                priority=40,
                key="perception.decision_reflex_tail",
            ),
        )


def build_perception_decision_system_section() -> Section[PerceptionDecisionPromptContext]:
    return Section(
        "perception_decision_system",
        separator="\n",
        children=(
            _PersonaSection("persona", priority=10),
            _SceneRuleSection("scene_rule", priority=20, separator=""),
            _ReflexRuleSection("reflex_rule", priority=30, separator=""),
            I18nSection(
                "json_footer",
                priority=40,
                key="perception.decision_json_footer",
            ),
        ),
    )


class _VisualObservationSection(Section[PerceptionDecisionPromptContext]):
    def _render_self(self, context: PerceptionDecisionPromptContext) -> str:
        anchor = (context.scene_anchor or context.previous_digest).strip()
        lines: list[str] = []
        if context.compared_frames:
            lines.append(context.tr("perception.decision_user_collage_hint"))
            if anchor:
                lines.append(
                    context.tr(
                        "perception.decision_user_collage_anchor",
                        anchor=anchor[:140],
                    )
                )
        elif anchor:
            lines.append(
                context.tr(
                    "perception.decision_user_prev_observation",
                    anchor=anchor[:160],
                )
            )
        return "\n".join(lines)


class _ScreenTextObservationSection(Section[PerceptionDecisionPromptContext]):
    def _render_self(self, context: PerceptionDecisionPromptContext) -> str:
        prior_subs = [
            line.strip() for line in context.recent_subtitles if line and line.strip()
        ]
        lines: list[str] = []
        if context.screen_text:
            clean_current_sub = context.screen_text.strip()
            if prior_subs and prior_subs[-1] == clean_current_sub:
                prior_subs = prior_subs[:-1]
            if not prior_subs and context.previous_screen_text and context.watching_screen:
                prior_subs = [context.previous_screen_text.strip()]
            if prior_subs and context.watching_screen:
                joined_prior = " / ".join(s[:90] for s in prior_subs[-3:])
                lines.append(
                    context.tr(
                        "perception.decision_user_prior_subs",
                        subs_json=json.dumps(joined_prior, ensure_ascii=False),
                    )
                )
            ocr_key = (
                "perception.decision_user_current_ocr_watching"
                if context.watching_screen
                else "perception.decision_user_current_ocr_game"
            )
            lines.append(
                context.tr(
                    ocr_key,
                    text_json=json.dumps(context.screen_text, ensure_ascii=False),
                )
            )
            if context.watching_screen and context.screen_text_changed is False:
                lines.append(context.tr("perception.decision_user_unchanged_sub_hint"))
        elif prior_subs and context.watching_screen:
            joined_prior = " / ".join(s[:90] for s in prior_subs[-3:])
            lines.append(
                context.tr(
                    "perception.decision_user_recent_subs_only",
                    subs_json=json.dumps(joined_prior, ensure_ascii=False),
                )
            )
        return "\n".join(lines)


class _RecentBarksSection(Section[PerceptionDecisionPromptContext]):
    def _render_self(self, context: PerceptionDecisionPromptContext) -> str:
        if not context.reflex_enabled:
            return ""
        spoken_barks = [b.strip() for b in context.recent_barks if b and b.strip()]
        if not spoken_barks:
            return ""
        joined = " / ".join(
            json.dumps(b[:30], ensure_ascii=False) for b in spoken_barks[-2:]
        )
        return context.tr("perception.decision_user_recent_barks", barks=joined)


class _GameTelemetrySection(Section[PerceptionDecisionPromptContext]):
    def _resolve_children(
        self,
        context: PerceptionDecisionPromptContext,
    ) -> tuple[Section[PerceptionDecisionPromptContext], ...]:
        children: list[Section[PerceptionDecisionPromptContext]] = []
        if context.compact_states_json:
            children.append(
                Section(
                    "states_block",
                    priority=10,
                    separator="\n",
                    children=(
                        I18nSection(
                            "states_header",
                            priority=10,
                            key="perception.decision_user_game_states_header",
                        ),
                        TextSection(
                            "states_payload",
                            priority=20,
                            text=context.compact_states_json,
                        ),
                    ),
                )
            )
        if context.compact_events_json:
            children.append(
                Section(
                    "events_block",
                    priority=20,
                    separator="\n",
                    children=(
                        I18nSection(
                            "events_header",
                            priority=10,
                            key="perception.decision_user_game_events_header",
                        ),
                        TextSection(
                            "events_payload",
                            priority=20,
                            text=context.compact_events_json,
                        ),
                    ),
                )
            )
        return tuple(children)


class _UserClosingSection(Section[PerceptionDecisionPromptContext]):
    def _render_self(self, context: PerceptionDecisionPromptContext) -> str:
        if context.watching_screen:
            return context.tr("perception.decision_user_closing_watching")
        if context.has_frame:
            return context.tr("perception.decision_user_closing_game_frame")
        return context.tr("perception.decision_user_closing_game_state")


def build_perception_decision_user_section() -> Section[PerceptionDecisionPromptContext]:
    return Section(
        "perception_decision_user",
        separator="\n",
        children=(
            TextSection(
                "limited_ocr",
                priority=10,
                text=lambda ctx: (
                    ctx.tr("perception.decision_user_limited_ocr")
                    if ctx.limited_ocr
                    else ""
                ),
            ),
            _VisualObservationSection("visual_obs", priority=20),
            _ScreenTextObservationSection("screen_text_obs", priority=30),
            _RecentBarksSection("recent_barks", priority=40),
            _GameTelemetrySection("game_telemetry", priority=50, separator="\n"),
            _UserClosingSection("closing", priority=60),
        ),
    )


# L3 small-model contract: Qwen3-VL-2B-Instruct decision prompts stay locked to zh_CN
# until small-model calibration unlocks additional locales.
PERCEPTION_DECISION_SPEC: PromptSpec[
    PerceptionDecisionPromptContext, PerceptionDecisionPromptContext
] = PromptSpec(
    id="perception.decision",
    language_policy=PromptLanguagePolicy.LOCKED_CONTRACT,
    locked_locale="zh_CN",
    system_builder=build_perception_decision_system_section,
    user_builder=build_perception_decision_user_section,
)


def render_focus_guidance_hint(focus_hint: str, *, locale: str | None = None) -> str:
    clean = str(focus_hint or "").strip()
    if not clean:
        return ""
    ctx = TemplateContext(
        locale=PERCEPTION_DECISION_SPEC.resolve_locale(locale),
    )
    return ctx.tr("perception.decision_focus_guidance", focus_hint=clean)


def format_compact_states_json(states: Mapping[str, Any] | None) -> str:
    if not states:
        return ""
    compact = json.dumps(states, ensure_ascii=False)
    return compact[:1597] + "..." if len(compact) > 1600 else compact


def format_compact_events_json(events: Sequence[Any]) -> str:
    if not events:
        return ""
    rows = [
        ev.to_compact_dict() if hasattr(ev, "to_compact_dict") else ev
        for ev in events[-12:]
    ]
    compact = json.dumps(rows, ensure_ascii=False)
    return compact[:1197] + "..." if len(compact) > 1200 else compact


def render_perception_decision_prompts(
    context: PerceptionDecisionPromptContext,
    *,
    respect_locked_contract: bool = True,
) -> tuple[str, str]:
    if respect_locked_contract:
        return (
            PERCEPTION_DECISION_SPEC.render_system(context),
            PERCEPTION_DECISION_SPEC.render_user(context),
        )
    normalized = normalize_lang(context.locale)
    ctx = (
        context
        if context.locale == normalized
        else PerceptionDecisionPromptContext(
            **{**context.__dict__, "locale": normalized}
        )
    )
    return (
        build_perception_decision_system_section().render(ctx),
        build_perception_decision_user_section().render(ctx),
    )


__all__ = [
    "PERCEPTION_DECISION_SPEC",
    "PerceptionDecisionPromptContext",
    "build_perception_decision_system_section",
    "build_perception_decision_user_section",
    "format_compact_events_json",
    "format_compact_states_json",
    "render_focus_guidance_hint",
    "render_perception_decision_prompts",
]

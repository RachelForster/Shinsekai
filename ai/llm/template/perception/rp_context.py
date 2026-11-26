"""Pure Composite prompt sections and translators for RP Vision Memory injection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sdk.lang import LocaleCode, Translator, normalize_lang

from ..core.catalog import PROMPT_CATALOG
from ..core.context import TemplateContext
from ..core.prompt_spec import PromptLanguagePolicy, PromptSpec
from ..core.section import I18nSection, Section, TextSection

PERCEPTION_CONTEXT_SENTINEL = "[Shinsekai realtime game perception cache]"


@dataclass(frozen=True)
class RpPerceptionContext(TemplateContext):
    """Structured projection of Vision Memory rendered for main RP turns."""

    active_game: str = ""
    overall_summary: str = ""
    recent_episodes: tuple[tuple[int, str], ...] = ()
    anchor: tuple[int, bool, str] | None = None
    visual_beats: tuple[tuple[str, int, str], ...] = ()
    subtitles: tuple[tuple[str, str], ...] = ()
    delta_mode: Literal["none", "stale", "fresh"] = "none"
    fresh_preview: str = ""
    player_busy: bool = False

    def has_observations(self) -> bool:
        return bool(
            self.overall_summary
            or self.recent_episodes
            or self.anchor is not None
            or self.visual_beats
            or self.subtitles
        )


class _RpPerceptionBodySection(Section[RpPerceptionContext]):
    def _resolve_children(
        self,
        context: RpPerceptionContext,
    ) -> tuple[Section[RpPerceptionContext], ...]:
        if not context.has_observations():
            return ()
        children: list[Section[RpPerceptionContext]] = []
        game_suffix = (
            context.tr("perception.rp_game_suffix", game=context.active_game)
            if context.active_game
            else ""
        )
        children.append(
            TextSection(
                "header",
                priority=10,
                text=f"{PERCEPTION_CONTEXT_SENTINEL}{game_suffix}",
            )
        )
        children.append(
            I18nSection("intro", priority=20, key="perception.rp_intro")
        )

        ep_lines: list[str] = []
        if context.overall_summary:
            ep_lines.append(
                context.tr("perception.rp_overall_item", summary=context.overall_summary)
            )
        for mins, summary in context.recent_episodes:
            ep_lines.append(
                context.tr("perception.rp_episode_item", mins=mins, summary=summary)
            )
        if ep_lines:
            children.append(
                Section(
                    "episodes",
                    priority=30,
                    separator="\n",
                    children=(
                        I18nSection(
                            "episodes_header",
                            priority=10,
                            key="perception.rp_episodes_header",
                        ),
                        TextSection(
                            "episodes_items",
                            priority=20,
                            text="\n".join(ep_lines),
                        ),
                    ),
                )
            )

        if context.anchor is not None:
            age, is_fresh, anchor_text = context.anchor
            anchor_key = (
                "perception.rp_anchor_fresh"
                if is_fresh
                else "perception.rp_anchor_carried"
            )
            children.append(
                I18nSection(
                    "anchor",
                    priority=40,
                    key=anchor_key,
                    params={"age": age, "text": anchor_text},
                )
            )

        if context.visual_beats:
            if len(context.visual_beats) == 1 and context.anchor is None:
                _kind, age, summary = context.visual_beats[0]
                children.append(
                    I18nSection(
                        "single_visual",
                        priority=50,
                        key="perception.rp_single_visual",
                        params={"age": age, "summary": summary},
                    )
                )
            else:
                detail_tag = context.tr("perception.rp_visual_detail_tag")
                cut_tag = context.tr("perception.rp_visual_cut_tag")
                beat_lines = "\n".join(
                    f"  * [{detail_tag if kind == 'detail' else cut_tag}] {summary}"
                    for kind, _age, summary in context.visual_beats
                )
                children.append(
                    Section(
                        "visual_list",
                        priority=50,
                        separator="\n",
                        children=(
                            I18nSection(
                                "visual_header",
                                priority=10,
                                key="perception.rp_visual_list_header",
                            ),
                            TextSection("visual_items", priority=20, text=beat_lines),
                        ),
                    )
                )

        if context.subtitles:
            source_map = {
                "highlight": context.tr("perception.source_highlight"),
                "subtitle": context.tr("perception.source_subtitle"),
                "cursor": context.tr("perception.source_cursor"),
            }
            sub_lines = "\n".join(
                f"  * [{source_map.get(src, source_map['subtitle'])}] {text}"
                for src, text in context.subtitles
            )
            children.append(
                Section(
                    "subtitles",
                    priority=60,
                    separator="\n",
                    children=(
                        I18nSection(
                            "subtitles_header",
                            priority=10,
                            key="perception.rp_subtitles_header",
                        ),
                        TextSection("subtitles_items", priority=20, text=sub_lines),
                    ),
                )
            )

        if context.delta_mode == "stale":
            children.append(
                I18nSection(
                    "stale_hint",
                    priority=70,
                    key="perception.rp_no_new_changes_hint",
                )
            )
        elif context.delta_mode == "fresh" and context.fresh_preview:
            children.append(
                I18nSection(
                    "fresh_hint",
                    priority=70,
                    key="perception.rp_fresh_delta_hint",
                    params={"preview": context.fresh_preview},
                )
            )

        if context.player_busy:
            children.append(
                I18nSection(
                    "player_busy",
                    priority=80,
                    key="perception.rp_player_busy",
                )
            )
        return tuple(children)


def build_rp_perception_section() -> Section[RpPerceptionContext]:
    return _RpPerceptionBodySection("perception_rp_context", separator="\n")


RP_PERCEPTION_CONTEXT_SPEC: PromptSpec[RpPerceptionContext, RpPerceptionContext] = (
    PromptSpec(
        id="perception.rp_context",
        language_policy=PromptLanguagePolicy.FOLLOW_UI,
        user_builder=build_rp_perception_section,
    )
)


def build_perception_translator(locale: str | None = None) -> Translator:
    """Return a stateless `Translator` bound to `locale` for `core.perception` injection."""
    resolved: LocaleCode = normalize_lang(locale) if locale else "zh_CN"
    return PROMPT_CATALOG.translator(resolved)


def render_proactive_turn_instruction(*, locale: str | None = None) -> str:
    resolved = normalize_lang(locale) if locale else "zh_CN"
    return PROMPT_CATALOG.translate(
        "perception.proactive_turn_instruction",
        locale=resolved,
    )


def render_proactive_collapsed_history(*, locale: str | None = None) -> str:
    resolved = normalize_lang(locale) if locale else "zh_CN"
    return PROMPT_CATALOG.translate(
        "perception.proactive_collapsed_history",
        locale=resolved,
    )


def render_perception_turn_reply_suffix(*, locale: str | None = None) -> str:
    resolved = normalize_lang(locale) if locale else "zh_CN"
    return PROMPT_CATALOG.translate(
        "perception.rp_turn_reply_suffix",
        locale=resolved,
    )


__all__ = [
    "PERCEPTION_CONTEXT_SENTINEL",
    "RP_PERCEPTION_CONTEXT_SPEC",
    "RpPerceptionContext",
    "build_perception_translator",
    "build_rp_perception_section",
    "render_perception_turn_reply_suffix",
    "render_proactive_collapsed_history",
    "render_proactive_turn_instruction",
]

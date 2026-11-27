"""Prompt, requirement, label, tool, and repair renderers for `renpy_v1`."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ai.llm.template.core import I18nSection, Section, TemplateContext, TextSection
from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT
from sdk.adapters.dialog_format import DialogFormatPromptContext
from sdk.lang import normalize_lang
from sdk.types import RequirementSpec

from ..prompt_support import render_repair_message, translate_dialog
from .sections import (
    RENPY_OUTFIT_PROMPT_SPEC,
    RENPY_PLAYER_PROMPT_SPEC,
    RENPY_REMINDER_PROMPT_SPEC,
    RENPY_SCHEMA_PROMPT_SPEC,
    RenpyOutfitContext,
    RenpyPlayerContext,
    RenpySchemaContext,
    render_renpy_format_reminder,
    render_renpy_outfit_hint,
    render_renpy_player_hint,
    render_renpy_schema_hint,
)


def render_renpy_label(*, locale: str = "zh_CN") -> str:
    """Return localized display label for `renpy_v1`."""
    return translate_dialog("format_label_renpy_v1", locale=locale)


def render_renpy_tool_protocol(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog(
        "closing_custom_tool_protocol", locale=locale, translate=translate
    )


def render_renpy_tools_intro(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog("custom_tools_intro", locale=locale, translate=translate)


def _system_directives(prompt: DialogFormatPromptContext) -> tuple[str, ...]:
    return tuple(
        cmd
        for enabled, cmd in (
            (prompt.use_cot, "cot:"),
            (prompt.has_real_background, "scene"),
            (prompt.has_real_background, "play music"),
            (prompt.use_narration, "narr"),
            (prompt.use_stat, "stat"),
            (prompt.use_cg, "cg"),
            (prompt.use_choice, "menu:"),
        )
        if enabled
    )


def _build_cname_section(context: DialogFormatPromptContext) -> Section[TemplateContext]:
    directives = _system_directives(context)
    if directives:
        tail: Section[TemplateContext] = I18nSection(
            id="directives",
            priority=30,
            key="dialog.renpy_r_cname_directives",
            params=lambda ctx: {
                "directives": ctx.tr("dialog.renpy_directive_sep").join(directives)
            },
        )
    else:
        tail = I18nSection(id="suffix", priority=30, key="dialog.renpy_r_cname_suffix")
    return Section(
        id="r_cname",
        separator="",
        children=(
            I18nSection(id="prefix", priority=10, key="dialog.renpy_r_cname_prefix"),
            TextSection(id="names", priority=20, text=context.names),
            tail,
        ),
    )


def render_renpy_requirements(context: DialogFormatPromptContext) -> list[RequirementSpec]:
    """Build switch-aware Ren'Py DSL requirements without format-injecting names."""
    loc = normalize_lang(context.locale)
    tr = context.translate
    translator = (
        (lambda k, **kw: translate_dialog(k, locale=loc, translate=tr, **kw))
        if tr is not None
        else None
    )
    base_ctx = TemplateContext(locale=loc, translator=translator)
    specs: tuple[tuple[str, int, bool, Section[TemplateContext]], ...] = (
        ("r_cot", 5, context.use_cot, I18nSection("r_cot", key="dialog.renpy_r_cot", params={"cot": COT})),
        ("r_format", 10, True, I18nSection("r_format", key="dialog.renpy_r_format")),
        ("r_user_display_name_tool", 15, True, I18nSection("r_user_display_name_tool", key="dialog.r_user_display_name_tool")),
        ("r_cname", 20, True, _build_cname_section(context)),
        (
            "r_sprite",
            30,
            not context.uses_vibe,
            I18nSection(
                "r_sprite",
                key="dialog.renpy_r_full_sprite" if context.uses_full_sprite_ids else "dialog.renpy_r_sprite",
            ),
        ),
        ("r_vibe", 30, context.uses_vibe, I18nSection("r_vibe", key="dialog.renpy_r_vibe")),
        (
            "r_scene",
            50,
            context.has_real_background,
            I18nSection(
                "r_scene",
                key="dialog.renpy_r_scene_vibe" if context.uses_vibe else "dialog.renpy_r_scene",
                params={"scn": SCENE},
            ),
        ),
        (
            "r_bgm",
            60,
            context.has_real_background,
            I18nSection(
                "r_bgm",
                key="dialog.renpy_r_bgm_vibe" if context.uses_vibe else "dialog.renpy_r_bgm",
                params={"bgm_t": BGM},
            ),
        ),
        (
            "r_speech",
            70,
            True,
            I18nSection(
                "r_speech",
                key="dialog.renpy_r_speech",
                params=lambda ctx: {"speech_lang_name": ctx.tr("dialog.renpy_speech_lang_name")},
            ),
        ),
        ("r_array", 80, True, I18nSection("r_array", key="dialog.renpy_r_sequence")),
        (
            "r_speech_max_chars",
            90,
            context.max_speech_chars > 0,
            I18nSection("r_speech_max_chars", key="dialog.renpy_r_speech_max_chars", params={"n": context.max_speech_chars}),
        ),
        (
            "r_dialog_max_items",
            95,
            context.max_dialog_items > 0,
            I18nSection("r_dialog_max_items", key="dialog.renpy_r_dialog_max_items", params={"n": context.max_dialog_items}),
        ),
        (
            "r_narration",
            100,
            context.use_narration,
            I18nSection(
                "r_narration",
                key="dialog.renpy_r_narration",
                params=lambda ctx: {"narr": ctx.tr("dialog.renpy_narr_token")},
            ),
        ),
        ("r_choice_pos", 110, context.use_choice, I18nSection("r_choice_pos", key="dialog.renpy_r_choice_pos", params={"choice": CHOICE})),
        ("r_choice_format", 120, context.use_choice, I18nSection("r_choice_format", key="dialog.renpy_r_choice_format", params={"choice": CHOICE})),
        ("r_choice_balance", 130, context.use_choice, I18nSection("r_choice_balance", key="dialog.renpy_r_choice_balance")),
        ("r_stats", 140, context.use_stat, I18nSection("r_stats", key="dialog.renpy_r_stats", params={"stat": STAT})),
        ("r_cg", 150, context.use_cg, I18nSection("r_cg", key="dialog.renpy_r_cg", params={"cg": CG})),
        (
            "r_translate",
            160,
            context.use_llm_translation,
            I18nSection("r_translate", key="dialog.renpy_r_translate", params={"target_voice_name": context.target_voice_name}),
        ),
        ("r_effect", 170, context.use_effect, I18nSection("r_effect", key="dialog.renpy_r_effect")),
        ("r_scene_transition", 172, context.has_real_background, I18nSection("r_scene_transition", key="dialog.renpy_r_scene_transition")),
        ("r_character_motion", 174, True, I18nSection("r_character_motion", key="dialog.renpy_r_character_motion")),
    )
    return [
        RequirementSpec(
            id=rule_id,
            text=section.render(base_ctx) if enabled else "",
            order=order,
            enabled=enabled,
        )
        for rule_id, order, enabled, section in specs
    ]


def render_renpy_repair_prompt(
    *,
    media_field: str,
    retry: bool,
    locale: str,
    allow_unbound_speakers: bool = False,
    bound_speakers: Sequence[str] = (),
) -> str:
    if allow_unbound_speakers:
        key = (
            "session.dialog_repair_renpy_retry_selective"
            if retry
            else "session.dialog_repair_renpy_initial_selective"
        )
    else:
        key = (
            "session.dialog_repair_renpy_retry"
            if retry
            else "session.dialog_repair_renpy_initial"
        )
    return render_repair_message(
        instruction_key=key,
        media_field=media_field,
        locale=locale,
        allow_unbound_speakers=allow_unbound_speakers,
        bound_speakers=bound_speakers,
    )


__all__ = [
    "RENPY_OUTFIT_PROMPT_SPEC",
    "RENPY_PLAYER_PROMPT_SPEC",
    "RENPY_REMINDER_PROMPT_SPEC",
    "RENPY_SCHEMA_PROMPT_SPEC",
    "RenpyOutfitContext",
    "RenpyPlayerContext",
    "RenpySchemaContext",
    "render_renpy_format_reminder",
    "render_renpy_label",
    "render_renpy_outfit_hint",
    "render_renpy_player_hint",
    "render_renpy_repair_prompt",
    "render_renpy_requirements",
    "render_renpy_schema_hint",
    "render_renpy_tool_protocol",
    "render_renpy_tools_intro",
]

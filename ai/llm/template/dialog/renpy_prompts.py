"""Requirement/repair renderers and provider registration for `renpy_v1`."""

from __future__ import annotations

from collections.abc import Sequence

from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT
from sdk.adapters.dialog_format import (
    DialogFormatPromptContext,
    DialogOutfitHint,
    DialogOutfitHintContext,
    DialogPlayerHintContext,
    RENPY_DIALOG_FORMAT_ID,
)
from sdk.lang import normalize_lang
from sdk.types import RequirementSpec

from ..core import I18nSection, Section, TemplateContext, TextSection
from .renpy_sections import (
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
    tail: Section[TemplateContext]
    if directives:
        tail = I18nSection(
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
    base_ctx = TemplateContext(locale=normalize_lang(context.locale))
    specs: tuple[tuple[str, int, bool, Section[TemplateContext]], ...] = (
        ("r_cot", 5, context.use_cot, I18nSection("r_cot", key="dialog.renpy_r_cot", params={"cot": COT})),
        ("r_format", 10, True, I18nSection("r_format", key="dialog.renpy_r_format")),
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
            text=section.render(base_ctx),
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
    from ..session.dialog_repair import (
        DIALOG_REPAIR_PROMPT_SPEC,
        DialogRepairPromptContext,
    )

    return DIALOG_REPAIR_PROMPT_SPEC.render_user(
        DialogRepairPromptContext(
            locale=normalize_lang(locale),
            media_field=media_field,
            retry=retry,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=tuple(bound_speakers),
            output_format_id=RENPY_DIALOG_FORMAT_ID,
        )
    )


class RenpyTemplatePromptProvider:
    """Adapter binding `PromptCatalog`-backed Section renderers to `RenpyDslDialogFormat`."""

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None:
        return render_renpy_schema_hint(
            media_field=media_field,
            translate_required=translate_required,
            locale=locale,
            prompt_context=prompt_context,
        )

    def render_requirements(
        self,
        context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None:
        return render_renpy_requirements(context)

    def render_outfit_hint(
        self,
        context: DialogOutfitHintContext,
    ) -> DialogOutfitHint | None:
        return render_renpy_outfit_hint(context)

    def render_player_hint(
        self,
        context: DialogPlayerHintContext,
    ) -> str | None:
        return render_renpy_player_hint(context)

    def render_format_reminder(self, *, locale: str) -> str | None:
        return render_renpy_format_reminder(locale=locale)

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None:
        return render_renpy_repair_prompt(
            media_field=media_field,
            retry=retry,
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
    "RenpyTemplatePromptProvider",
    "render_renpy_format_reminder",
    "render_renpy_outfit_hint",
    "render_renpy_player_hint",
    "render_renpy_repair_prompt",
    "render_renpy_requirements",
    "render_renpy_schema_hint",
]

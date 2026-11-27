"""Declarative Section/I18nSection/PromptSpec builders for Ren'Py DSL prompts."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.messaging.formats.renpy import format_renpy_speaker
from core.messaging.formats.renpy.lexer import quote_dsl_string
from sdk.adapters.dialog_format import (
    DialogFormatPromptContext,
    DialogOutfitHint,
    DialogOutfitHintContext,
    DialogPlayerHintContext,
)
from sdk.lang import normalize_lang

from ..core import I18nSection, PromptSpec, Section, TemplateContext, TextSection


@dataclass(frozen=True)
class RenpySchemaContext(TemplateContext):
    """Render context for the opening Ren'Py DSL schema block."""

    prompt: DialogFormatPromptContext = field(default_factory=DialogFormatPromptContext)
    variant: str = "indexed"
    effect_enabled: bool = False
    trans_enabled: bool = False


@dataclass(frozen=True)
class RenpyPlayerContext(TemplateContext):
    """Render context for Ren'Py player-character control rules."""

    player: DialogPlayerHintContext = field(default_factory=DialogPlayerHintContext)


@dataclass(frozen=True)
class RenpyOutfitContext(TemplateContext):
    """Render context for Ren'Py outfit-switching instructions."""

    auto_switch_enabled: bool = True


class _RenpySchemaSection(Section[RenpySchemaContext]):
    def _resolve_children(
        self,
        context: RenpySchemaContext,
    ) -> tuple[Section[RenpySchemaContext], ...]:
        prompt = context.prompt
        variant = context.variant
        return (
            I18nSection("intro", priority=10, key="dialog.renpy_schema_intro"),
            I18nSection("cot", priority=20, enabled=prompt.use_cot, key="dialog.renpy_example_cot"),
            I18nSection("scene", priority=30, enabled=prompt.has_real_background, key=f"dialog.renpy_example_scene_{variant}"),
            I18nSection("bgm", priority=35, enabled=prompt.has_real_background, key=f"dialog.renpy_example_bgm_{variant}"),
            I18nSection(
                "say",
                priority=40,
                key=f"dialog.renpy_example_say_{variant}",
                params=lambda ctx: {
                    "effect_attr": ctx.tr("dialog.renpy_example_effect_attr") if ctx.effect_enabled else "",
                    "trans_part": (
                        ctx.tr("dialog.renpy_example_trans_part", target_voice_name=ctx.prompt.target_voice_name)
                        if ctx.trans_enabled
                        else ""
                    ),
                },
            ),
            I18nSection("narr", priority=50, enabled=prompt.use_narration, key="dialog.renpy_example_narr"),
            I18nSection("stat", priority=55, enabled=prompt.use_stat, key="dialog.renpy_example_stat"),
            I18nSection("cg", priority=60, enabled=prompt.use_cg, key="dialog.renpy_example_cg"),
            I18nSection("choice", priority=65, enabled=prompt.use_choice, key="dialog.renpy_example_choice"),
            I18nSection("effect_note", priority=70, enabled=context.effect_enabled, key="dialog.renpy_line_effect"),
            I18nSection(
                "trans_note",
                priority=75,
                enabled=context.trans_enabled,
                key="dialog.renpy_line_trans",
                params=lambda ctx: {"target_voice_name": ctx.prompt.target_voice_name},
            ),
            I18nSection(
                "stage_effects",
                priority=80,
                key="dialog.renpy_stage_effects" if prompt.has_real_background else "dialog.renpy_stage_effects_motion_only",
            ),
            I18nSection("foot", priority=90, key="dialog.renpy_schema_foot"),
        )


def _build_renpy_schema_section() -> Section[RenpySchemaContext]:
    return _RenpySchemaSection(id="dialog.renpy_schema", separator="\n")


def _build_renpy_reminder_section() -> Section[TemplateContext]:
    return I18nSection(id="dialog.renpy_reminder", key="dialog.renpy_closing_reminder")


class _RenpyOutfitSection(Section[RenpyOutfitContext]):
    def _resolve_children(
        self,
        context: RenpyOutfitContext,
    ) -> tuple[Section[RenpyOutfitContext], ...]:
        key = "session.outfit_switch_rule_renpy" if context.auto_switch_enabled else "session.outfit_locked_rule_renpy"
        return (I18nSection(id="rule", priority=10, key=key),)


def _build_renpy_outfit_section() -> Section[RenpyOutfitContext]:
    return _RenpyOutfitSection(id="session.renpy_outfit")


class _RenpyPlayerSection(Section[RenpyPlayerContext]):
    def _resolve_children(
        self,
        context: RenpyPlayerContext,
    ) -> tuple[Section[RenpyPlayerContext], ...]:
        player = context.player
        speaker = format_renpy_speaker(player.name)
        allow = bool(player.allow_player_dialogue)
        heading = Section(
            id="heading",
            priority=10,
            separator="",
            children=(
                I18nSection(
                    id="label",
                    priority=10,
                    key="dialog.renpy_player_ai_heading" if allow else "dialog.renpy_player_control_heading",
                ),
                TextSection(id="name", priority=20, text=player.name),
            ),
        )
        setting_text = str(player.setting or "").strip()
        setting_section = TextSection(id="setting", priority=20, enabled=bool(setting_text), text=setting_text)
        if allow:
            return (
                heading,
                setting_section,
                I18nSection(
                    id="ai_rules",
                    priority=30,
                    key="dialog.renpy_player_ai_rules",
                    params={"portrait_field": player.portrait_field, "portrait_value": player.portrait_value},
                ),
                Section(
                    id="ai_example",
                    priority=40,
                    separator="",
                    children=(
                        I18nSection(id="prefix", priority=10, key="dialog.renpy_player_ai_example_prefix"),
                        TextSection(
                            id="sample",
                            priority=20,
                            text=f'`{speaker} [{player.portrait_field}="..."] "..."` / `{speaker} [{player.portrait_field}="{player.portrait_value}"] ""`',
                        ),
                    ),
                ),
            )

        speech_media = 'vibe=""' if player.uses_vibe else 'sprite="-1"'
        speech_node: Section[RenpyPlayerContext]
        if player.read_player_speech:
            speech_node = Section(
                id="speech",
                priority=20,
                separator="",
                children=(
                    I18nSection(id="prefix", priority=10, key="dialog.renpy_player_speech_contract_prefix"),
                    TextSection(id="speaker", priority=20, text=speaker),
                    I18nSection(
                        id="suffix",
                        priority=30,
                        key="dialog.renpy_player_speech_contract_suffix",
                        params={"speech_media": speech_media, "target_voice_name": player.target_voice_name},
                    ),
                ),
            )
        else:
            speech_node = I18nSection(id="speech", priority=20, key="dialog.renpy_player_speech_disabled")

        details = Section(
            id="details",
            priority=40,
            separator="\n",
            children=(
                Section(
                    id="portrait",
                    priority=10,
                    separator="",
                    children=(
                        I18nSection(id="prefix", priority=10, key="dialog.renpy_player_control_portrait_prefix"),
                        TextSection(id="sample", priority=20, text=f'`{speaker} [{player.portrait_field}="{player.portrait_value}"] ""`'),
                        I18nSection(id="suffix", priority=30, key="dialog.renpy_player_control_portrait_suffix"),
                    ),
                ),
                speech_node,
                I18nSection(id="footer", priority=30, key="dialog.renpy_player_control_footer"),
            ),
        )
        return (
            heading,
            setting_section,
            I18nSection(id="intro", priority=30, key="dialog.renpy_player_control_intro"),
            details,
        )


def _build_renpy_player_section() -> Section[RenpyPlayerContext]:
    return _RenpyPlayerSection(id="dialog.renpy_player", separator="\n\n")


RENPY_SCHEMA_PROMPT_SPEC = PromptSpec(id="dialog.renpy_schema", user_builder=_build_renpy_schema_section)
RENPY_REMINDER_PROMPT_SPEC = PromptSpec(id="dialog.renpy_reminder", user_builder=_build_renpy_reminder_section)
RENPY_OUTFIT_PROMPT_SPEC = PromptSpec(id="session.renpy_outfit", user_builder=_build_renpy_outfit_section)
RENPY_PLAYER_PROMPT_SPEC = PromptSpec(id="dialog.renpy_player", user_builder=_build_renpy_player_section)


def render_renpy_schema_hint(
    *,
    media_field: str,
    translate_required: bool,
    locale: str,
    prompt_context: DialogFormatPromptContext | None = None,
) -> str:
    """Render the opening Ren'Py DSL schema block via I18nSection + PromptSpec."""
    prompt = prompt_context or DialogFormatPromptContext(
        locale=locale,
        media_field=media_field,
        uses_vibe=(media_field == "vibe"),
        use_llm_translation=translate_required,
    )
    removed = set(prompt.removed_optional_fields)
    variant = "vibe" if prompt.uses_vibe else ("full" if prompt.uses_full_sprite_ids else "indexed")
    ctx = RenpySchemaContext(
        locale=normalize_lang(prompt.locale or locale),
        prompt=prompt,
        variant=variant,
        effect_enabled=bool(prompt.use_effect and "effect" not in removed),
        trans_enabled=bool(prompt.use_llm_translation and "translate" not in removed),
    )
    return RENPY_SCHEMA_PROMPT_SPEC.render_user(ctx)


def render_renpy_format_reminder(*, locale: str) -> str:
    return RENPY_REMINDER_PROMPT_SPEC.render_user(TemplateContext(locale=normalize_lang(locale))).rstrip()


def render_renpy_outfit_hint(context: DialogOutfitHintContext) -> DialogOutfitHint:
    rule_text = RENPY_OUTFIT_PROMPT_SPEC.render_user(
        RenpyOutfitContext(locale=normalize_lang(context.locale), auto_switch_enabled=bool(context.auto_switch_enabled))
    )
    if context.auto_switch_enabled and context.example_character and context.example_target_group:
        media_attr = f"vibe={quote_dsl_string(context.example_vibe)}" if context.media_selection_mode == "semantic" else 'sprite="-1"'
        example = (
            f"{format_renpy_speaker(context.example_character)} "
            f"[{media_attr}, outfit={quote_dsl_string(context.example_target_group)}] "
            f"{quote_dsl_string(context.example_speech)}"
        )
        return DialogOutfitHint(rule_text=rule_text, example_line=example)
    return DialogOutfitHint(rule_text=rule_text, example_line="")


def render_renpy_player_hint(context: DialogPlayerHintContext) -> str:
    rendered = RENPY_PLAYER_PROMPT_SPEC.render_user(
        RenpyPlayerContext(locale=normalize_lang(context.locale), player=context)
    ).strip("\n")
    return f"\n{rendered}\n\n" if rendered else ""


__all__ = [
    "RENPY_OUTFIT_PROMPT_SPEC",
    "RENPY_PLAYER_PROMPT_SPEC",
    "RENPY_REMINDER_PROMPT_SPEC",
    "RENPY_SCHEMA_PROMPT_SPEC",
    "RenpyOutfitContext",
    "RenpyPlayerContext",
    "RenpySchemaContext",
    "render_renpy_format_reminder",
    "render_renpy_outfit_hint",
    "render_renpy_player_hint",
    "render_renpy_schema_hint",
]

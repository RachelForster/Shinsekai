"""Prompt, requirement, outfit, player, reminder, and repair renderers for `xml_v1`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from xml.sax.saxutils import escape as xml_escape, quoteattr as xml_quoteattr

from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT
from sdk.adapters.dialog_format import (
    DialogFormatPromptContext,
    DialogOutfitHint,
    DialogOutfitHintContext,
    DialogPlayerHintContext,
)
from sdk.types import RequirementSpec

from ..prompt_support import (
    render_outfit_hint_from_key,
    render_repair_message,
    translate_dialog,
)


def render_xml_label(*, locale: str = "zh_CN") -> str:
    """Return localized display label for `xml_v1`."""
    return translate_dialog("format_label_xml_v1", locale=locale)


def render_xml_schema_hint(
    *,
    media_field: str,
    translate_required: bool,
    locale: str,
    prompt_context: DialogFormatPromptContext | None = None,
) -> str:
    """Render the opening XML/HTML stage tag schema block."""
    prompt = prompt_context or DialogFormatPromptContext(
        locale=locale,
        media_field=media_field,
        uses_vibe=(media_field == "vibe"),
        use_llm_translation=translate_required,
    )
    loc = str(prompt.locale or locale or "zh_CN")
    tr = prompt.translate
    removed = set(prompt.removed_optional_fields)

    if prompt.uses_vibe:
        variant = "vibe"
    elif prompt.uses_full_sprite_ids:
        variant = "full"
    else:
        variant = "indexed"
    effect_enabled = bool(prompt.use_effect and "effect" not in removed)
    trans_enabled = bool(prompt.use_llm_translation and "translate" not in removed)

    lines: list[str] = [translate_dialog("xml_schema_intro", locale=loc, translate=tr) + "\n"]
    if prompt.use_cot:
        lines.append(translate_dialog("xml_example_cot", locale=loc, translate=tr) + "\n")
    if prompt.has_real_background:
        lines.append(
            translate_dialog(f"xml_example_scene_{variant}", locale=loc, translate=tr) + "\n"
        )
        lines.append(
            translate_dialog(f"xml_example_bgm_{variant}", locale=loc, translate=tr) + "\n"
        )
    effect_attr = (
        translate_dialog("xml_example_effect_attr", locale=loc, translate=tr)
        if effect_enabled
        else ""
    )
    trans_tag = (
        translate_dialog(
            "xml_example_trans_tag",
            locale=loc,
            translate=tr,
            target_voice_name=prompt.target_voice_name,
        )
        if trans_enabled
        else ""
    )
    lines.append(
        translate_dialog(
            f"xml_example_say_{variant}",
            locale=loc,
            translate=tr,
            effect_attr=effect_attr,
            trans_tag=trans_tag,
        )
        + "\n"
    )
    if prompt.use_narration:
        lines.append(translate_dialog("xml_example_narr", locale=loc, translate=tr) + "\n")
    if prompt.use_stat:
        lines.append(translate_dialog("xml_example_stat", locale=loc, translate=tr) + "\n")
    if prompt.use_cg:
        lines.append(translate_dialog("xml_example_cg", locale=loc, translate=tr) + "\n")
    if prompt.use_choice:
        lines.append(translate_dialog("xml_example_choice", locale=loc, translate=tr) + "\n")
    if effect_enabled:
        lines.append(translate_dialog("xml_line_effect", locale=loc, translate=tr) + "\n")
    if trans_enabled:
        lines.append(
            translate_dialog(
                "xml_line_trans",
                locale=loc,
                translate=tr,
                target_voice_name=prompt.target_voice_name,
            )
            + "\n"
        )
    lines.append(
        translate_dialog(
            "xml_stage_effects"
            if prompt.has_real_background
            else "xml_stage_effects_motion_only",
            locale=loc,
            translate=tr,
        )
        + "\n"
    )
    lines.append(translate_dialog("xml_foot", locale=loc, translate=tr) + "\n")
    return "".join(lines)


def render_xml_requirements(context: DialogFormatPromptContext) -> list[RequirementSpec]:
    """Build switch-aware XML/HTML requirements without eagerly translating disabled entries."""
    locale = str(context.locale or "zh_CN")
    tr = context.translate
    tokens = {
        "choice": CHOICE,
        "stat": STAT,
        "scn": SCENE,
        "bgm_t": BGM,
        "cg": CG,
        "cot": COT,
    }
    xml_system_tags = tuple(
        tag
        for enabled, tag in (
            (context.use_cot, "<cot>"),
            (context.has_real_background, "<scene>"),
            (context.has_real_background, "<bgm>"),
            (context.use_narration, "<narr>"),
            (context.use_stat, "<stat>"),
            (context.use_cg, "<cg>"),
            (context.use_choice, "<choice>"),
        )
        if enabled
    )

    def _cname_args() -> dict[str, Any]:
        if not xml_system_tags:
            return {"names": context.names}
        sep = translate_dialog("name_sep", locale=locale, translate=tr)
        return {
            "names": context.names,
            "xml_tags": sep.join(xml_system_tags),
        }

    definitions: tuple[tuple[str, int, bool, str, Callable[[], dict[str, Any]]], ...] = (
        ("r_cot", 5, context.use_cot, "xml_r_cot", lambda: tokens),
        ("r_format", 10, True, "xml_r_format", dict),
        ("r_user_display_name_tool", 15, True, "r_user_display_name_tool", dict),
        (
            "r_cname",
            20,
            True,
            "xml_r_cname" if xml_system_tags else "xml_r_cname_say_only",
            _cname_args,
        ),
        (
            "r_sprite",
            30,
            not context.uses_vibe,
            "r_full_sprite" if context.uses_full_sprite_ids else "r_sprite",
            dict,
        ),
        ("r_vibe", 30, context.uses_vibe, "r_vibe", dict),
        (
            "r_scene",
            50,
            context.has_real_background,
            "xml_r_scene_vibe" if context.uses_vibe else "xml_r_scene",
            lambda: tokens,
        ),
        (
            "r_bgm",
            60,
            context.has_real_background,
            "xml_r_bgm_vibe" if context.uses_vibe else "xml_r_bgm",
            lambda: tokens,
        ),
        (
            "r_speech",
            70,
            True,
            "r_speech",
            lambda: {
                "speech_lang_name": translate_dialog(
                    "speech_lang_name",
                    locale=locale,
                    translate=tr,
                )
            },
        ),
        ("r_array", 80, True, "xml_r_sequence", dict),
        (
            "r_speech_max_chars",
            90,
            context.max_speech_chars > 0,
            "r_speech_max_chars",
            lambda: {"n": context.max_speech_chars},
        ),
        (
            "r_dialog_max_items",
            95,
            context.max_dialog_items > 0,
            "xml_r_dialog_max_items",
            lambda: {"n": context.max_dialog_items},
        ),
        (
            "r_narration",
            100,
            context.use_narration,
            "xml_r_narration",
            lambda: {
                "narr": translate_dialog("narr_token", locale=locale, translate=tr)
            },
        ),
        ("r_choice_pos", 110, context.use_choice, "xml_r_choice_pos", lambda: tokens),
        ("r_choice_format", 120, context.use_choice, "xml_r_choice_format", lambda: tokens),
        ("r_choice_balance", 130, context.use_choice, "r_choice_balance", lambda: tokens),
        ("r_stats", 140, context.use_stat, "xml_r_stats", lambda: tokens),
        ("r_cg", 150, context.use_cg, "xml_r_cg", lambda: tokens),
        (
            "r_translate",
            160,
            context.use_llm_translation,
            "xml_r_translate",
            lambda: {"target_voice_name": context.target_voice_name},
        ),
        ("r_effect", 170, context.use_effect, "xml_r_effect", dict),
        (
            "r_scene_transition",
            172,
            context.has_real_background,
            "xml_r_scene_transition",
            dict,
        ),
        ("r_character_motion", 174, True, "xml_r_character_motion", dict),
    )

    specs: list[RequirementSpec] = []
    for rule_id, order, enabled, key, args_fn in definitions:
        text = (
            translate_dialog(key, locale=locale, translate=tr, **args_fn())
            if enabled
            else ""
        )
        specs.append(
            RequirementSpec(
                id=rule_id,
                text=text,
                order=order,
                enabled=enabled,
            )
        )
    return specs


def render_xml_outfit_hint(context: DialogOutfitHintContext) -> DialogOutfitHint:
    """Render localized XML/HTML outfit-switching instructions and example `<say>` tag."""
    if not context.auto_switch_enabled:
        return render_outfit_hint_from_key(
            rule_key="session.outfit_locked_or_disabled_rule_xml",
            locale=context.locale,
        )
    example_line = ""
    if context.example_character and context.example_target_group:
        media_attr = (
            f"vibe={xml_quoteattr(context.example_vibe)}"
            if context.media_selection_mode == "semantic"
            else 'sprite="-1"'
        )
        example_line = (
            f"<say char={xml_quoteattr(context.example_character)} "
            f"{media_attr} "
            f"outfit={xml_quoteattr(context.example_target_group)}>"
            f"{xml_escape(context.example_speech)}</say>"
        )
    return render_outfit_hint_from_key(
        rule_key="session.outfit_auto_switch_rule_xml",
        locale=context.locale,
        example_line=example_line,
    )


def render_xml_player_hint(context: DialogPlayerHintContext) -> str:
    """Render XML/HTML player-character control instructions."""
    locale = str(context.locale or "zh_CN")
    tr = context.translate
    if context.allow_player_dialogue:
        return translate_dialog(
            "xml_player_ai_control",
            locale=locale,
            translate=tr,
            name=context.name,
            setting=context.setting,
            portrait_field=context.portrait_field,
            portrait_value=context.portrait_value,
        )
    speech_media = 'vibe=""' if context.uses_vibe else 'sprite="-1"'
    speech_contract = (
        translate_dialog(
            "xml_player_speech_contract",
            locale=locale,
            translate=tr,
            name=context.name,
            speech_media=speech_media,
            target_voice_name=context.target_voice_name,
        )
        if context.read_player_speech
        else translate_dialog(
            "player_speech_disabled",
            locale=locale,
            translate=tr,
            name=context.name,
        )
    )
    return translate_dialog(
        "xml_player_control",
        locale=locale,
        translate=tr,
        name=context.name,
        setting=context.setting,
        portrait_field=context.portrait_field,
        portrait_value=context.portrait_value,
        speech_contract=speech_contract,
    )


def render_xml_format_reminder(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog("closing_xml_reminder", locale=locale, translate=translate)


def render_xml_tool_protocol(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog(
        "closing_xml_tool_protocol", locale=locale, translate=translate
    )


def render_xml_tools_intro(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog("xml_tools_intro", locale=locale, translate=translate)


def render_xml_repair_prompt(
    *,
    media_field: str,
    retry: bool,
    locale: str,
    allow_unbound_speakers: bool = False,
    bound_speakers: Sequence[str] = (),
) -> str:
    key = (
        "session.dialog_repair_xml_retry"
        if retry
        else "session.dialog_repair_xml_initial"
    )
    return render_repair_message(
        instruction_key=key,
        media_field=media_field,
        locale=locale,
        allow_unbound_speakers=allow_unbound_speakers,
        bound_speakers=bound_speakers,
    )


__all__ = [
    "render_xml_format_reminder",
    "render_xml_label",
    "render_xml_outfit_hint",
    "render_xml_player_hint",
    "render_xml_repair_prompt",
    "render_xml_requirements",
    "render_xml_schema_hint",
    "render_xml_tool_protocol",
    "render_xml_tools_intro",
]

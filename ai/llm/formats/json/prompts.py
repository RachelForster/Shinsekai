"""Prompt, requirement, outfit, player, reminder, and repair renderers for `json_v1`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from typing import Any

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


def _json_string_content(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def render_json_label(*, locale: str = "zh_CN") -> str:
    """Return localized display label for `json_v1`."""
    return translate_dialog("format_label_json_v1", locale=locale)


def render_json_schema_hint(
    *,
    media_field: str,
    translate_required: bool,
    locale: str,
    prompt_context: DialogFormatPromptContext | None = None,
) -> str:
    """Render the opening JSON schema block matching the classic contract verbatim."""
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
        head_key = "json_vibe_head_top"
    elif prompt.uses_full_sprite_ids:
        head_key = "json_full_sprite_head_top"
    else:
        head_key = "json_head_top"

    parts: list[str] = [
        translate_dialog(head_key, locale=loc, translate=tr),
        translate_dialog(
            "json_speech_line",
            locale=loc,
            translate=tr,
            example=_json_string_content(
                translate_dialog("json_speech_example", locale=loc, translate=tr)
            ),
        ),
    ]
    if prompt.use_effect and "effect" not in removed:
        parts.append(translate_dialog("json_line_effect", locale=loc, translate=tr))
    if prompt.use_llm_translation and "translate" not in removed:
        parts.append(
            translate_dialog(
                "json_line_trans",
                locale=loc,
                translate=tr,
                target_voice_name=_json_string_content(prompt.target_voice_name),
            )
        )
    parts.append(translate_dialog("json_foot", locale=loc, translate=tr))
    return "".join(part for part in parts if part)


def _build_cname_args(
    context: DialogFormatPromptContext,
    *,
    locale: str,
    translate: Callable[..., str] | None,
) -> dict[str, str]:
    fixed_parts: list[str] = []
    if context.use_narration:
        fixed_parts.append(translate_dialog("narr_token", locale=locale, translate=translate))
    if context.use_choice:
        fixed_parts.append(CHOICE)
    if context.use_stat:
        fixed_parts.append(STAT)
    fixed_roles = "、".join(part for part in fixed_parts if part)
    return {
        "names": context.names,
        "cot_part": f"{COT}," if context.use_cot else "",
        "fixed_roles": f" {fixed_roles}" if fixed_roles else "",
        "opt_scene": f", {SCENE}" if context.has_real_background else "",
        "opt_bgm": f", {BGM}" if context.has_real_background else "",
        "opt_cg": f", {CG}" if context.use_cg else "",
    }


def render_json_requirements(context: DialogFormatPromptContext) -> list[RequirementSpec]:
    """Build switch-aware JSON requirements without eagerly translating disabled entries."""
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

    def _fixed_roles_text() -> str:
        parts: list[str] = []
        if context.use_narration:
            parts.append(translate_dialog("narr_token", locale=locale, translate=tr))
        if context.use_choice:
            parts.append(CHOICE)
        if context.use_stat:
            parts.append(STAT)
        return "、".join(part for part in parts if part)

    definitions: tuple[tuple[str, int, bool, str, Callable[[], dict[str, Any]]], ...] = (
        ("r_cot", 5, context.use_cot, "r_cot", lambda: tokens),
        ("r_format", 10, True, "r_format", dict),
        ("r_user_display_name_tool", 15, True, "r_user_display_name_tool", dict),
        (
            "r_cname",
            20,
            True,
            "r_cname",
            lambda: _build_cname_args(context, locale=locale, translate=tr),
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
            "r_non_sprite",
            40,
            True,
            "r_non_vibe" if context.uses_vibe else "r_non_sprite",
            lambda: {"fixed_roles_non_sprite": _fixed_roles_text()},
        ),
        (
            "r_scene",
            50,
            context.has_real_background,
            "r_scene_vibe" if context.uses_vibe else "r_scene",
            lambda: tokens,
        ),
        (
            "r_bgm",
            60,
            context.has_real_background,
            "r_bgm_vibe" if context.uses_vibe else "r_bgm",
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
        ("r_array", 80, True, "r_array", dict),
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
            "r_dialog_max_items",
            lambda: {"n": context.max_dialog_items},
        ),
        (
            "r_narration",
            100,
            context.use_narration,
            "r_narration",
            lambda: {
                "narr": translate_dialog("narr_token", locale=locale, translate=tr)
            },
        ),
        ("r_choice_pos", 110, context.use_choice, "r_choice_pos", lambda: tokens),
        ("r_choice_format", 120, context.use_choice, "r_choice_format", lambda: tokens),
        ("r_choice_balance", 130, context.use_choice, "r_choice_balance", lambda: tokens),
        ("r_stats", 140, context.use_stat, "r_stats", lambda: tokens),
        ("r_cg", 150, context.use_cg, "r_cg", lambda: tokens),
        (
            "r_translate",
            160,
            context.use_llm_translation,
            "r_translate",
            lambda: {"target_voice_name": context.target_voice_name},
        ),
        ("r_effect", 170, context.use_effect, "r_effect", dict),
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


def render_json_outfit_hint(context: DialogOutfitHintContext) -> DialogOutfitHint:
    """Render localized JSON outfit-switching instructions and example JSON item."""
    if not context.auto_switch_enabled:
        return render_outfit_hint_from_key(
            rule_key="session.outfit_locked_or_disabled_rule",
            locale=context.locale,
        )
    example_line = ""
    if context.example_character and context.example_target_group:
        media = (
            {"vibe": context.example_vibe}
            if context.media_selection_mode == "semantic"
            else {"sprite": "-1"}
        )
        payload = {
            "character_name": context.example_character,
            **media,
            "speech": context.example_speech,
            "outfit": context.example_target_group,
        }
        example_line = json.dumps(payload, ensure_ascii=False)
    return render_outfit_hint_from_key(
        rule_key="session.outfit_auto_switch_rule",
        locale=context.locale,
        example_line=example_line,
    )


def render_json_player_hint(context: DialogPlayerHintContext) -> str:
    """Render JSON-format player-character control instructions."""
    locale = str(context.locale or "zh_CN")
    tr = context.translate
    if context.allow_player_dialogue:
        return translate_dialog(
            "player_ai_control",
            locale=locale,
            translate=tr,
            name=context.name,
            setting=context.setting,
            portrait_field=context.portrait_field,
            portrait_value=context.portrait_value,
        )
    speech_media = '"vibe":""' if context.uses_vibe else '"sprite":"-1"'
    speech_contract = (
        translate_dialog(
            "player_speech_contract",
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
        "player_control",
        locale=locale,
        translate=tr,
        name=context.name,
        setting=context.setting,
        portrait_field=context.portrait_field,
        portrait_value=context.portrait_value,
        speech_contract=speech_contract,
    )


def render_json_format_reminder(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog("closing_json_reminder", locale=locale, translate=translate)


def render_json_tool_protocol(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog("closing_tool_protocol", locale=locale, translate=translate)


def render_json_tools_intro(
    *,
    locale: str,
    translate: Callable[..., str] | None = None,
) -> str:
    return translate_dialog("tools_intro", locale=locale, translate=translate)


def render_json_repair_prompt(
    *,
    media_field: str,
    retry: bool,
    locale: str,
    allow_unbound_speakers: bool = False,
    bound_speakers: Sequence[str] = (),
) -> str:
    if allow_unbound_speakers:
        key = (
            "session.dialog_repair_retry_selective"
            if retry
            else "session.dialog_repair_initial_selective"
        )
    else:
        key = (
            "session.dialog_repair_retry"
            if retry
            else "session.dialog_repair_initial"
        )
    return render_repair_message(
        instruction_key=key,
        media_field=media_field,
        locale=locale,
        allow_unbound_speakers=allow_unbound_speakers,
        bound_speakers=bound_speakers,
    )


__all__ = [
    "render_json_format_reminder",
    "render_json_label",
    "render_json_outfit_hint",
    "render_json_player_hint",
    "render_json_repair_prompt",
    "render_json_requirements",
    "render_json_schema_hint",
    "render_json_tool_protocol",
    "render_json_tools_intro",
]

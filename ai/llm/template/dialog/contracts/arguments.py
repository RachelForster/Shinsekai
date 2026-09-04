"""Compose localized rule arguments from enabled token sections."""

from typing import Any

from core.messaging.dialog_tokens import BGM, CG, CHOICE, COT, SCENE, STAT

from ...core import Section, TextSection
from ..context import DialogTemplateContext


def requirement_arguments(context: DialogTemplateContext) -> dict[str, dict[str, Any]]:
    tokens = {
        "narr": context.translate("narr_token"),
        "choice": CHOICE,
        "stat": STAT,
        "scn": SCENE,
        "bgm_t": BGM,
        "cg": CG,
        "cot": COT,
    }
    fixed_roles = Section(
        "fixed_roles",
        separator="、",
        children=(
            TextSection("narr", text=tokens["narr"], enabled=context.use_narration),
            TextSection("choice", text=CHOICE, enabled=context.use_choice),
            TextSection("stat", text=STAT, enabled=context.use_stat),
        ),
    ).render(context)
    optional_tokens = (
        TextSection("cot_part", text=f"{COT},", enabled=context.use_cot),
        TextSection("fixed_roles", text=f" {fixed_roles}", enabled=bool(fixed_roles)),
        TextSection(
            "opt_scene", text=f", {SCENE}", enabled=context.has_real_background
        ),
        TextSection("opt_bgm", text=f", {BGM}", enabled=context.has_real_background),
        TextSection("opt_cg", text=f", {CG}", enabled=context.use_cg),
    )
    token_rules = (
        "r_scene",
        "r_bgm",
        "r_narration",
        "r_choice_pos",
        "r_choice_format",
        "r_choice_balance",
        "r_stats",
        "r_cg",
        "r_cot",
    )
    return {
        **dict.fromkeys(token_rules, tokens),
        "r_cname": {
            "names": context.names,
            **{section.id: section.render(context) for section in optional_tokens},
        },
        "r_non_sprite": {"fixed_roles_non_sprite": fixed_roles},
        "r_speech": {"speech_lang_name": context.translate("speech_lang_name")},
        "r_speech_max_chars": {"n": context.max_speech_chars},
        "r_dialog_max_items": {"n": context.max_dialog_items},
        "r_translate": {"target_voice_name": context.target_voice_name},
    }

"""Application-facing helpers for pluggable LLM dialog output formats."""

from __future__ import annotations

from typing import Any

from ai.llm.template.core import PROMPT_CATALOG
from ai.llm.template.dialog.renpy_prompts import ensure_renpy_prompt_provider_registered
from core.messaging.formats.registry import (
    get_dialog_format,
    is_builtin_dialog_format,
    registered_dialog_formats,
    resolve_dialog_format,
)
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogOutfitHintContext,
    XML_DIALOG_FORMAT_ID,
)
from sdk.lang import normalize_lang


def normalize_output_format(
    value: object,
    *,
    default: str = DEFAULT_DIALOG_FORMAT_ID,
) -> str:
    """Return a registered dialog output format id, or `default` when blank/unknown."""
    candidate = str(value or "").strip().lower()
    if not candidate:
        return default
    if is_builtin_dialog_format(candidate) or get_dialog_format(candidate) is not None:
        return candidate
    return default


def resolve_outfit_format_hint(
    *,
    output_format: str,
    locale: str,
    media_selection_mode: str,
    auto_switch_enabled: bool,
    example_character: str = "",
    example_target_group: str = "",
) -> tuple[str, str]:
    """Resolve optional outfit-switch instructions via DialogOutputFormat hooks."""
    fmt_id = str(output_format or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
    if not fmt_id or fmt_id in (DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID):
        return "", ""
    ensure_renpy_prompt_provider_registered()
    fmt = resolve_dialog_format(fmt_id)
    if fmt.format_id in (DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID):
        return "", ""
    resolved_locale = normalize_lang(locale)
    hint = fmt.render_outfit_hint(
        DialogOutfitHintContext(
            locale=resolved_locale,
            media_selection_mode=media_selection_mode,
            auto_switch_enabled=bool(auto_switch_enabled),
            example_character=example_character,
            example_target_group=example_target_group,
            example_vibe=PROMPT_CATALOG.translate(
                "session.outfit_example_vibe",
                locale=resolved_locale,
            ),
            example_speech=PROMPT_CATALOG.translate(
                "session.outfit_example_speech",
                locale=resolved_locale,
            ),
        )
    )
    if hint is None or not str(hint.rule_text or "").strip():
        return "", ""
    rule_text = hint.rule_text.strip()
    raw_example = str(hint.example_line or "").strip()
    if not raw_example:
        return rule_text, ""
    prefix = PROMPT_CATALOG.translate(
        "session.outfit_switch_example_prefix",
        locale=resolved_locale,
    )
    rendered_example = (
        raw_example
        if (not prefix or raw_example.startswith(prefix))
        else f"{prefix}{raw_example}"
    )
    return rule_text, rendered_example


def list_dialog_formats() -> list[dict[str, Any]]:
    """Return UI-consumable descriptors for all registered dialog output formats."""
    return [
        {
            "id": fmt.format_id,
            "label": fmt.label or fmt.format_id,
            "builtin": is_builtin_dialog_format(fmt.format_id),
        }
        for fmt in registered_dialog_formats()
    ]

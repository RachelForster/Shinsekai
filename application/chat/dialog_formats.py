"""Application-facing helpers for pluggable LLM dialog output formats."""

from __future__ import annotations

from typing import Any

from ai.llm.formats import (
    get_dialog_format,
    is_builtin_dialog_format,
    registered_dialog_formats,
    resolve_dialog_format,
)
from ai.llm.template.core import PROMPT_CATALOG
from i18n import current_language
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogOutfitHintContext,
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
    """Resolve outfit-switch instructions uniformly via DialogOutputFormat hooks."""
    fmt_id = str(output_format or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
    fmt = resolve_dialog_format(fmt_id)
    resolved_locale = normalize_lang(locale)
    hint_ctx = DialogOutfitHintContext(
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
    hint = fmt.render_outfit_hint(hint_ctx)
    if hint is None and fmt.format_id != DEFAULT_DIALOG_FORMAT_ID:
        hint = resolve_dialog_format(DEFAULT_DIALOG_FORMAT_ID).render_outfit_hint(
            hint_ctx
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


def list_dialog_formats(*, locale: str | None = None) -> list[dict[str, Any]]:
    """Return UI-consumable descriptors for all registered dialog output formats."""
    resolved_locale = normalize_lang(locale or current_language())
    rows: list[dict[str, Any]] = []
    for fmt in registered_dialog_formats():
        label = ""
        render_label = getattr(fmt, "render_label", None)
        if callable(render_label):
            try:
                label = str(render_label(locale=resolved_locale) or "").strip()
            except TypeError:
                label = str(render_label() or "").strip()
        rows.append(
            {
                "id": fmt.format_id,
                "label": label or fmt.label or fmt.format_id,
                "builtin": is_builtin_dialog_format(fmt.format_id),
            }
        )
    return rows

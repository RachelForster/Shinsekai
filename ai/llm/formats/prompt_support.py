"""Shared prompt-catalog translation and declarative repair/outfit helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ai.llm.template.core import (
    PROMPT_CATALOG,
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)
from sdk.adapters.dialog_format import DialogOutfitHint
from sdk.lang import normalize_lang


def translate_dialog(
    key: str,
    *,
    locale: str = "zh_CN",
    translate: Callable[..., str] | None = None,
    **kwargs: Any,
) -> str:
    """Translate a `dialog.*` key via custom translator override or `PROMPT_CATALOG`."""
    short_key = key[len("dialog.") :] if key.startswith("dialog.") else key
    if translate is not None:
        return str(translate(short_key, **kwargs))
    return PROMPT_CATALOG.translate(
        f"dialog.{short_key}",
        locale=normalize_lang(locale),
        **kwargs,
    )


@dataclass(frozen=True)
class RepairPromptContext(TemplateContext):
    """Render context for malformed-response repair instructions."""

    instruction_key: str = "session.dialog_repair_initial"
    media_field: str = "sprite"
    allow_unbound_speakers: bool = False
    bound_speakers: tuple[str, ...] = ()


class _RepairInstructionSection(Section[RepairPromptContext]):
    def _resolve_children(
        self,
        context: RepairPromptContext,
    ) -> tuple[Section[RepairPromptContext], ...]:
        children: list[Section[RepairPromptContext]] = [
            I18nSection(
                id="instruction",
                priority=10,
                key=context.instruction_key,
                params=lambda ctx: {"media_field": ctx.media_field},
            ),
        ]
        speakers = tuple(
            cleaned
            for raw in context.bound_speakers
            if (cleaned := str(raw or "").strip())
        )
        if context.allow_unbound_speakers and speakers:
            children.append(
                Section(
                    id="bound_speakers",
                    priority=20,
                    separator="\n",
                    children=(
                        I18nSection(
                            id="heading",
                            priority=10,
                            key="session.dialog_repair_bound_speakers_heading",
                            params=lambda ctx: {"media_field": ctx.media_field},
                        ),
                        TextSection(
                            id="names",
                            priority=20,
                            text=", ".join(speakers),
                        ),
                    ),
                )
            )
        return tuple(children)


REPAIR_MESSAGE_SPEC = PromptSpec(
    id="formats.dialog_repair",
    user_builder=lambda: _RepairInstructionSection(
        id="formats.dialog_repair.user",
        separator="\n\n",
    ),
)


def render_repair_message(
    *,
    instruction_key: str,
    media_field: str,
    locale: str,
    allow_unbound_speakers: bool = False,
    bound_speakers: Sequence[str] = (),
) -> str:
    """Render a localized dialog repair instruction via `PromptSpec`."""
    return REPAIR_MESSAGE_SPEC.render_user(
        RepairPromptContext(
            locale=normalize_lang(locale),
            instruction_key=instruction_key,
            media_field=media_field,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=tuple(bound_speakers),
        )
    )


@dataclass(frozen=True)
class _OutfitRuleContext(TemplateContext):
    rule_key: str = "session.outfit_auto_switch_rule"


OUTFIT_RULE_SPEC = PromptSpec(
    id="formats.outfit_rule",
    system_builder=lambda: I18nSection(
        id="rule",
        key="session.outfit_auto_switch_rule",
    ),
)


class _DynamicOutfitRuleSection(Section[_OutfitRuleContext]):
    def _resolve_children(
        self,
        context: _OutfitRuleContext,
    ) -> tuple[Section[_OutfitRuleContext], ...]:
        return (I18nSection(id="rule", priority=10, key=context.rule_key),)


_DYNAMIC_OUTFIT_RULE_SPEC = PromptSpec(
    id="formats.outfit_rule.dynamic",
    system_builder=lambda: _DynamicOutfitRuleSection(id="formats.outfit_rule.section"),
)


def render_outfit_hint_from_key(
    *,
    rule_key: str,
    locale: str,
    example_line: str = "",
) -> DialogOutfitHint:
    """Render a localized outfit rule (`session.*`) paired with a format example."""
    rule_text = _DYNAMIC_OUTFIT_RULE_SPEC.render_system(
        _OutfitRuleContext(locale=normalize_lang(locale), rule_key=rule_key)
    )
    return DialogOutfitHint(rule_text=rule_text, example_line=example_line)


__all__ = [
    "REPAIR_MESSAGE_SPEC",
    "RepairPromptContext",
    "render_outfit_hint_from_key",
    "render_repair_message",
    "translate_dialog",
]

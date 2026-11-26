"""Pure localized turn-context injection blocks with stable ASCII protocol sentinels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any
from xml.sax.saxutils import escape as xml_escape, quoteattr as xml_quoteattr

from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)

MEMORY_CONTEXT_MARKER = "[Shinsekai:memory]"
LEGACY_MEMORY_CONTEXT_MARKERS: tuple[str, ...] = (
    "[Shinsekai long-term memory context]",
)
ALL_MEMORY_CONTEXT_MARKERS: tuple[str, ...] = (
    MEMORY_CONTEXT_MARKER,
    *LEGACY_MEMORY_CONTEXT_MARKERS,
)

KNOWLEDGE_CONTEXT_MARKER = "[Shinsekai:knowledge]"
LEGACY_KNOWLEDGE_CONTEXT_MARKERS: tuple[str, ...] = (
    "[Shinsekai knowledge context]",
)
ALL_KNOWLEDGE_CONTEXT_MARKERS: tuple[str, ...] = (
    KNOWLEDGE_CONTEXT_MARKER,
    *LEGACY_KNOWLEDGE_CONTEXT_MARKERS,
)

OUTFIT_CONTEXT_MARKER = "[Shinsekai:outfit]"
LEGACY_OUTFIT_CONTEXT_MARKERS: tuple[str, ...] = (
    "[当前角色服装分组状态]",
)
ALL_OUTFIT_CONTEXT_MARKERS: tuple[str, ...] = (
    OUTFIT_CONTEXT_MARKER,
    *LEGACY_OUTFIT_CONTEXT_MARKERS,
)

RELATION_CONTEXT_MARKER = "[Shinsekai:relation]"
LEGACY_RELATION_CONTEXT_MARKERS: tuple[str, ...] = (
    "[Shinsekai character relation context]",
)
ALL_RELATION_CONTEXT_MARKERS: tuple[str, ...] = (
    RELATION_CONTEXT_MARKER,
    *LEGACY_RELATION_CONTEXT_MARKERS,
)


def contains_any_context_marker(
    messages: Sequence[Mapping[str, Any]],
    markers: Sequence[str],
) -> bool:
    """Return True if any message content contains one of the canonical or legacy sentinels."""
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = str(message.get("content") or "")
        if any(marker in content for marker in markers):
            return True
    return False


def strip_system_messages_with_markers(
    messages: list[dict[str, Any]],
    markers: Sequence[str],
) -> None:
    """In-place remove system context blocks matching canonical or legacy sentinels."""
    prefixes = tuple(markers)
    messages[:] = [
        msg
        for msg in messages
        if not (
            isinstance(msg, Mapping)
            and msg.get("role") == "system"
            and isinstance(msg.get("content"), str)
            and msg["content"].lstrip().startswith(prefixes)
        )
    ]


def _bullet_lines(items: Sequence[str]) -> str:
    lines: list[str] = []
    for raw in items:
        text = str(raw or "").strip()
        if not text:
            continue
        lines.append(text if text.startswith("- ") else f"- {text}")
    return "\n".join(lines)


@dataclass(frozen=True)
class MemoryContextPromptContext(TemplateContext):
    items: tuple[str, ...] = ()
    tiered: bool = False


class _MemoryContextSection(Section[MemoryContextPromptContext]):
    def _resolve_children(
        self,
        context: MemoryContextPromptContext,
    ) -> tuple[Section[MemoryContextPromptContext], ...]:
        bullets = _bullet_lines(context.items)
        if not bullets:
            return ()
        guidance_key = (
            "session.memory_context_tiered_guidance"
            if context.tiered
            else "session.memory_context_simple_guidance"
        )
        return (
            TextSection(id="sentinel", priority=10, text=MEMORY_CONTEXT_MARKER),
            I18nSection(id="guidance", priority=20, key=guidance_key),
            TextSection(id="items", priority=30, text=bullets),
        )


def build_memory_context_section() -> Section[MemoryContextPromptContext]:
    return _MemoryContextSection(id="session.context.memory", separator="\n")


MEMORY_CONTEXT_SPEC = PromptSpec(
    id="session.context.memory",
    system_builder=build_memory_context_section,
)


@dataclass(frozen=True)
class KnowledgeContextPromptContext(TemplateContext):
    items: tuple[str, ...] = ()


class _KnowledgeContextSection(Section[KnowledgeContextPromptContext]):
    def _resolve_children(
        self,
        context: KnowledgeContextPromptContext,
    ) -> tuple[Section[KnowledgeContextPromptContext], ...]:
        bullets = _bullet_lines(context.items)
        if not bullets:
            return ()
        return (
            TextSection(
                id="header",
                priority=10,
                text=lambda ctx: f"{KNOWLEDGE_CONTEXT_MARKER} {ctx.tr('session.knowledge_context_header')}",
            ),
            TextSection(id="items", priority=20, text=bullets),
        )


def build_knowledge_context_section() -> Section[KnowledgeContextPromptContext]:
    return _KnowledgeContextSection(id="session.context.knowledge", separator="\n")


KNOWLEDGE_CONTEXT_SPEC = PromptSpec(
    id="session.context.knowledge",
    system_builder=build_knowledge_context_section,
)


@dataclass(frozen=True)
class OutfitCharacterEntry:
    name: str
    active_group: str
    locked: bool
    groups: tuple[str, ...]
    sprite_tag_items: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class OutfitContextPromptContext(TemplateContext):
    entries: tuple[OutfitCharacterEntry, ...] = ()
    media_selection_mode: str = "indexed"
    switch_example_character: str = ""
    switch_example_target_group: str = ""
    output_format_id: str = DEFAULT_DIALOG_FORMAT_ID


def _render_outfit_example_line(context: OutfitContextPromptContext) -> str:
    prefix = context.tr("session.outfit_switch_example_prefix")
    example_speech = context.tr("session.outfit_example_speech")
    is_xml = (
        str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
        == XML_DIALOG_FORMAT_ID
    )
    if is_xml:
        media_attr = (
            f"vibe={xml_quoteattr(context.tr('session.outfit_example_vibe'))}"
            if context.media_selection_mode == "semantic"
            else 'sprite="-1"'
        )
        return (
            prefix
            + f"<say char={xml_quoteattr(context.switch_example_character)} "
            + f"{media_attr} "
            + f"outfit={xml_quoteattr(context.switch_example_target_group)}>"
            + f"{xml_escape(example_speech)}</say>"
        )
    media = (
        {"vibe": context.tr("session.outfit_example_vibe")}
        if context.media_selection_mode == "semantic"
        else {"sprite": "-1"}
    )
    payload = {
        "character_name": context.switch_example_character,
        **media,
        "speech": example_speech,
        "outfit": context.switch_example_target_group,
    }
    return prefix + json.dumps(payload, ensure_ascii=False)


def _render_outfit_entries(context: OutfitContextPromptContext) -> str:
    lines: list[str] = []
    default_tag = context.tr("session.outfit_default_tag")
    for item in context.entries:
        lock_desc = context.tr(
            "session.outfit_lock_status_locked"
            if item.locked
            else "session.outfit_lock_status_unlocked"
        )
        entry_text = context.tr(
            "session.outfit_character_entry",
            name=item.name,
            active_group=item.active_group,
            lock_desc=lock_desc,
            groups=" / ".join(item.groups),
        )
        if context.media_selection_mode != "semantic" and item.sprite_tag_items:
            formatted_tags = ", ".join(
                f"{sprite_id}: {tag_text or default_tag}"
                for sprite_id, tag_text in item.sprite_tag_items
            )
            entry_text += "\n" + context.tr(
                "session.outfit_group_sprites_line",
                active_group=item.active_group,
                items=formatted_tags,
            )
        lines.append(entry_text)
    return "\n".join(lines)


class _OutfitContextSection(Section[OutfitContextPromptContext]):
    def _resolve_children(
        self,
        context: OutfitContextPromptContext,
    ) -> tuple[Section[OutfitContextPromptContext], ...]:
        if not context.entries:
            return ()
        children: list[Section[OutfitContextPromptContext]] = [
            TextSection(
                id="header",
                priority=10,
                text=lambda ctx: f"{OUTFIT_CONTEXT_MARKER} {ctx.tr('session.outfit_header_title')}",
            ),
            I18nSection(
                id="scope_rule",
                priority=20,
                key="session.outfit_scope_rule",
            ),
        ]
        if context.media_selection_mode != "semantic":
            children.append(
                I18nSection(
                    id="sprite_rule",
                    priority=30,
                    key="session.outfit_indexed_sprite_rule",
                )
            )
        is_xml = (
            str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
            == XML_DIALOG_FORMAT_ID
        )
        if context.switch_example_character and context.switch_example_target_group:
            children.append(
                I18nSection(
                    id="switch_rule",
                    priority=40,
                    key=(
                        "session.outfit_auto_switch_rule_xml"
                        if is_xml
                        else "session.outfit_auto_switch_rule"
                    ),
                )
            )
            children.append(
                TextSection(
                    id="switch_example",
                    priority=45,
                    text=_render_outfit_example_line,
                )
            )
        else:
            children.append(
                I18nSection(
                    id="locked_rule",
                    priority=40,
                    key=(
                        "session.outfit_locked_or_disabled_rule_xml"
                        if is_xml
                        else "session.outfit_locked_or_disabled_rule"
                    ),
                )
            )
        children.append(
            TextSection(
                id="entries",
                priority=50,
                text=_render_outfit_entries,
            )
        )
        return tuple(children)


def build_outfit_context_section() -> Section[OutfitContextPromptContext]:
    return _OutfitContextSection(id="session.context.outfit", separator="\n")


OUTFIT_CONTEXT_SPEC = PromptSpec(
    id="session.context.outfit",
    system_builder=build_outfit_context_section,
)


@dataclass(frozen=True)
class RelationContextPromptContext(TemplateContext):
    rendered_relations: str = ""


class _RelationContextSection(Section[RelationContextPromptContext]):
    def _resolve_children(
        self,
        context: RelationContextPromptContext,
    ) -> tuple[Section[RelationContextPromptContext], ...]:
        body = context.rendered_relations.strip()
        if not body:
            return ()
        return (
            TextSection(id="sentinel", priority=10, text=RELATION_CONTEXT_MARKER),
            TextSection(id="relations", priority=20, text=body),
        )


def build_relation_context_section() -> Section[RelationContextPromptContext]:
    return _RelationContextSection(id="session.context.relation", separator="\n")


RELATION_CONTEXT_SPEC = PromptSpec(
    id="session.context.relation",
    system_builder=build_relation_context_section,
)

__all__ = [
    "ALL_KNOWLEDGE_CONTEXT_MARKERS",
    "ALL_MEMORY_CONTEXT_MARKERS",
    "ALL_OUTFIT_CONTEXT_MARKERS",
    "ALL_RELATION_CONTEXT_MARKERS",
    "KNOWLEDGE_CONTEXT_MARKER",
    "KNOWLEDGE_CONTEXT_SPEC",
    "KnowledgeContextPromptContext",
    "LEGACY_KNOWLEDGE_CONTEXT_MARKERS",
    "LEGACY_MEMORY_CONTEXT_MARKERS",
    "LEGACY_OUTFIT_CONTEXT_MARKERS",
    "LEGACY_RELATION_CONTEXT_MARKERS",
    "MEMORY_CONTEXT_MARKER",
    "MEMORY_CONTEXT_SPEC",
    "MemoryContextPromptContext",
    "OUTFIT_CONTEXT_MARKER",
    "OUTFIT_CONTEXT_SPEC",
    "OutfitCharacterEntry",
    "OutfitContextPromptContext",
    "RELATION_CONTEXT_MARKER",
    "RELATION_CONTEXT_SPEC",
    "RelationContextPromptContext",
    "build_knowledge_context_section",
    "build_memory_context_section",
    "build_outfit_context_section",
    "build_relation_context_section",
    "contains_any_context_marker",
    "strip_system_messages_with_markers",
]

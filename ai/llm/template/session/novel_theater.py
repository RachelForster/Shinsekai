"""Pure localized prompt builders for Novel Theater direction, chunk feeds, and compaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)
from sdk.lang import normalize_lang


@dataclass(frozen=True)
class NovelDirectorCastEntry:
    source_name: str
    target_character: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class NovelDirectorContext(TemplateContext):
    cast_entries: tuple[NovelDirectorCastEntry, ...] = ()


@dataclass(frozen=True)
class NovelChunkFeedContext(TemplateContext):
    chapter_num: int = 1
    total_chapters: int = 1
    chapter_title: str = ""
    chunk_num: int = 1
    total_chunks: int = 1
    source_text: str = ""
    lookahead_text: str = ""


@dataclass(frozen=True)
class NovelCompactContext(TemplateContext):
    cast_summary: str = ""


def _render_cast_roster(context: NovelDirectorContext) -> str:
    if not context.cast_entries:
        return context.tr("session.novel_director_cast_empty")
    arrow = context.tr("session.novel_director_cast_actor_arrow")
    unbound = context.tr("session.novel_director_cast_unbound")
    aliases_label = context.tr("session.novel_director_cast_aliases_label")
    comma = context.tr("session.list_sep_comma")
    lines: list[str] = []
    for entry in context.cast_entries:
        line = f"- {entry.source_name}"
        if entry.aliases:
            line += f" ({aliases_label}{comma.join(entry.aliases)})"
        if entry.target_character:
            line += arrow
        else:
            line += unbound
        lines.append(line)
    return "\n".join(lines)


class _ChunkLookaheadSection(Section[NovelChunkFeedContext]):
    def _resolve_children(
        self,
        context: NovelChunkFeedContext,
    ) -> tuple[Section[NovelChunkFeedContext], ...]:
        if not str(context.lookahead_text or "").strip():
            return ()
        return (
            I18nSection(
                id="heading",
                priority=10,
                key="session.novel_chunk_lookahead_heading",
            ),
            TextSection(
                id="text",
                priority=20,
                text=lambda ctx: str(ctx.lookahead_text or "").strip(),
            ),
            I18nSection(
                id="rule",
                priority=30,
                key="session.novel_chunk_lookahead_rule",
            ),
        )


class _CompactCastSection(Section[NovelCompactContext]):
    def _resolve_children(
        self,
        context: NovelCompactContext,
    ) -> tuple[Section[NovelCompactContext], ...]:
        if not str(context.cast_summary or "").strip():
            return ()
        return (
            I18nSection(
                id="heading",
                priority=10,
                key="session.novel_compact_cast_heading",
            ),
            TextSection(
                id="summary",
                priority=20,
                text=lambda ctx: str(ctx.cast_summary or "").strip(),
            ),
        )


def build_novel_director_section() -> Section[NovelDirectorContext]:
    return Section(
        id="session.novel_director",
        separator="\n\n",
        children=(
            Section(
                id="header_and_rules",
                priority=10,
                separator="\n",
                children=(
                    I18nSection(
                        id="heading",
                        priority=10,
                        key="session.novel_director_heading",
                    ),
                    I18nSection(
                        id="rules",
                        priority=20,
                        key="session.novel_director_rules",
                    ),
                ),
            ),
            Section(
                id="cast_roster",
                priority=20,
                separator="\n",
                children=(
                    I18nSection(
                        id="heading",
                        priority=10,
                        key="session.novel_director_cast_heading",
                    ),
                    TextSection(
                        id="lines",
                        priority=20,
                        text=_render_cast_roster,
                    ),
                ),
            ),
        ),
    )


def build_novel_chunk_feed_section() -> Section[NovelChunkFeedContext]:
    return Section(
        id="session.novel_chunk",
        separator="\n\n",
        children=(
            Section(
                id="meta",
                priority=10,
                separator="\n",
                children=(
                    I18nSection(
                        id="header",
                        priority=10,
                        key="session.novel_chunk_header",
                        params=lambda ctx: {
                            "chapter_num": ctx.chapter_num,
                            "total_chapters": ctx.total_chapters,
                            "chunk_num": ctx.chunk_num,
                            "total_chunks": ctx.total_chunks,
                        },
                    ),
                    TextSection(
                        id="chapter_title",
                        priority=20,
                        text=lambda ctx: str(ctx.chapter_title or "").strip(),
                    ),
                ),
            ),
            Section(
                id="source",
                priority=20,
                separator="\n",
                children=(
                    I18nSection(
                        id="heading",
                        priority=10,
                        key="session.novel_chunk_source_heading",
                    ),
                    TextSection(
                        id="text",
                        priority=20,
                        text=lambda ctx: str(ctx.source_text or "").strip(),
                    ),
                ),
            ),
            _ChunkLookaheadSection(
                id="lookahead",
                priority=30,
                separator="\n",
            ),
        ),
    )


def build_novel_compact_section() -> Section[NovelCompactContext]:
    return Section(
        id="session.novel_compact",
        separator="\n",
        children=(
            I18nSection(
                id="base",
                priority=10,
                key="session.novel_compact_instruction",
            ),
            _CompactCastSection(
                id="cast",
                priority=20,
                separator=" ",
            ),
        ),
    )


NOVEL_DIRECTOR_SPEC = PromptSpec(
    id="session.novel_director",
    user_builder=build_novel_director_section,
)
NOVEL_CHUNK_FEED_SPEC = PromptSpec(
    id="session.novel_chunk_feed",
    user_builder=build_novel_chunk_feed_section,
)
NOVEL_COMPACT_SPEC = PromptSpec(
    id="session.novel_compact",
    user_builder=build_novel_compact_section,
)


def build_novel_pure_dialog_section() -> Section[TemplateContext]:
    return Section(
        id="session.novel_pure_dialog",
        separator="\n",
        children=(
            I18nSection(
                id="head_top",
                priority=10,
                key="dialog.json_head_top",
            ),
            I18nSection(
                id="speech_line",
                priority=20,
                key="dialog.json_speech_line",
                params=lambda ctx: {"example": ctx.tr("dialog.json_speech_example")},
            ),
            I18nSection(
                id="foot",
                priority=30,
                key="dialog.json_foot",
            ),
            I18nSection(
                id="req_header",
                priority=40,
                key="dialog.requirements_header",
            ),
            I18nSection(
                id="r_format",
                priority=50,
                key="dialog.r_format",
            ),
            I18nSection(
                id="r_narration",
                priority=60,
                key="dialog.r_narration",
                params=lambda ctx: {"narr": ctx.tr("dialog.narr_token")},
            ),
            I18nSection(
                id="r_array",
                priority=70,
                key="dialog.r_array",
            ),
            I18nSection(
                id="closing",
                priority=80,
                key="dialog.closing_json_reminder",
            ),
        ),
    )


NOVEL_PURE_DIALOG_SPEC = PromptSpec(
    id="session.novel_pure_dialog",
    system_builder=build_novel_pure_dialog_section,
)


def render_novel_pure_dialog_system(*, locale: str | None = None) -> str:
    """Render minimal JSON-dialog system contract when casting has zero bound sprites."""
    return NOVEL_PURE_DIALOG_SPEC.render_system(
        TemplateContext(locale=normalize_lang(locale))
    )


def render_novel_director_prompt(
    cast_entries: Sequence[Mapping[str, Any]],
    *,
    locale: str | None = None,
) -> str:
    """Render the system scenario instructions for Novel Theater direction."""
    entries: list[NovelDirectorCastEntry] = []
    for raw in cast_entries:
        source_name = str(raw.get("sourceName") or raw.get("source_name") or "").strip()
        if not source_name:
            continue
        target = str(
            raw.get("targetCharacter") or raw.get("target_character") or ""
        ).strip()
        raw_aliases = raw.get("aliases") or ()
        aliases = tuple(
            cleaned
            for alias in raw_aliases
            if (cleaned := str(alias or "").strip()) and cleaned != source_name
        )
        entries.append(
            NovelDirectorCastEntry(
                source_name=source_name,
                target_character=target,
                aliases=aliases,
            )
        )
    context = NovelDirectorContext(
        locale=normalize_lang(locale),
        cast_entries=tuple(entries),
    )
    return NOVEL_DIRECTOR_SPEC.render_user(context)


def render_novel_chunk_feed_prompt(
    *,
    chapter_num: int,
    total_chapters: int,
    chapter_title: str,
    chunk_num: int,
    total_chunks: int,
    source_text: str,
    lookahead_text: str = "",
    locale: str | None = None,
) -> str:
    """Render one chunk turn prompt with strict read-only lookahead disambiguation."""
    context = NovelChunkFeedContext(
        locale=normalize_lang(locale),
        chapter_num=max(1, int(chapter_num)),
        total_chapters=max(1, int(total_chapters)),
        chapter_title=str(chapter_title or "").strip(),
        chunk_num=max(1, int(chunk_num)),
        total_chunks=max(1, int(total_chunks)),
        source_text=str(source_text or ""),
        lookahead_text=str(lookahead_text or ""),
    )
    return NOVEL_CHUNK_FEED_SPEC.render_user(context)


def render_novel_compact_instruction(
    *,
    cast_summary: str = "",
    locale: str | None = None,
) -> str:
    """Render compaction instructions preserving characters, aliases, and plot continuity."""
    context = NovelCompactContext(
        locale=normalize_lang(locale),
        cast_summary=str(cast_summary or "").strip(),
    )
    return NOVEL_COMPACT_SPEC.render_user(context)


__all__ = [
    "NOVEL_CHUNK_FEED_SPEC",
    "NOVEL_COMPACT_SPEC",
    "NOVEL_DIRECTOR_SPEC",
    "NOVEL_PURE_DIALOG_SPEC",
    "NovelChunkFeedContext",
    "NovelCompactContext",
    "NovelDirectorCastEntry",
    "NovelDirectorContext",
    "build_novel_chunk_feed_section",
    "build_novel_compact_section",
    "build_novel_director_section",
    "build_novel_pure_dialog_section",
    "render_novel_chunk_feed_prompt",
    "render_novel_compact_instruction",
    "render_novel_director_prompt",
    "render_novel_pure_dialog_system",
]

"""Pure localized prompt section for TTS expressiveness capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID

from ai.llm.template.core import (
    I18nSection,
    PromptSpec,
    Section,
    TemplateContext,
    TextSection,
)

TTS_STYLE_CONTEXT_MARKER = "[Shinsekai:tts_style]"
ALL_TTS_STYLE_CONTEXT_MARKERS: tuple[str, ...] = (TTS_STYLE_CONTEXT_MARKER,)


@dataclass(frozen=True)
class TtsStyleContextPromptContext(TemplateContext):
    """Capabilities declared by the active TTS adapter and active output format."""

    supports_inline_voice_tags: bool = False
    supports_voice_instruction: bool = False
    output_format_id: str = DEFAULT_DIALOG_FORMAT_ID


class _TtsStyleContextSection(Section[TtsStyleContextPromptContext]):
    def _resolve_children(
        self,
        context: TtsStyleContextPromptContext,
    ) -> tuple[Section[TtsStyleContextPromptContext], ...]:
        if not (context.supports_inline_voice_tags or context.supports_voice_instruction):
            return ()

        fmt_id = str(context.output_format_id or DEFAULT_DIALOG_FORMAT_ID).strip().lower()
        if fmt_id == XML_DIALOG_FORMAT_ID:
            channel_key = "session.tts_style_inline_tags_channel_xml"
            instruct_key = "session.tts_style_voice_instruct_xml"
        elif fmt_id == DEFAULT_DIALOG_FORMAT_ID:
            channel_key = "session.tts_style_inline_tags_channel_json"
            instruct_key = "session.tts_style_voice_instruct_json"
        else:
            channel_key = "session.tts_style_inline_tags_channel_custom"
            instruct_key = "session.tts_style_voice_instruct_custom"

        children: list[Section[TtsStyleContextPromptContext]] = [
            TextSection(
                id="header",
                priority=10,
                text=lambda ctx: f"{TTS_STYLE_CONTEXT_MARKER} {ctx.tr('session.tts_style_header')}",
            )
        ]
        if context.supports_inline_voice_tags:
            children.append(
                I18nSection(
                    id="inline_tags_rule",
                    priority=20,
                    key="session.tts_style_inline_tags_rule",
                )
            )
            children.append(
                I18nSection(
                    id="inline_tags_channel",
                    priority=30,
                    key=channel_key,
                )
            )
        if context.supports_voice_instruction:
            children.append(
                I18nSection(
                    id="voice_instruct_rule",
                    priority=40,
                    key=instruct_key,
                )
            )
        return tuple(children)


def build_tts_style_context_section() -> Section[TtsStyleContextPromptContext]:
    """Return the composite section rendering active TTS style capabilities."""
    return _TtsStyleContextSection(id="session.context.tts_style", separator="\n")


TTS_STYLE_CONTEXT_SPEC = PromptSpec(
    id="session.context.tts_style",
    system_builder=build_tts_style_context_section,
)


__all__ = [
    "ALL_TTS_STYLE_CONTEXT_MARKERS",
    "TTS_STYLE_CONTEXT_MARKER",
    "TTS_STYLE_CONTEXT_SPEC",
    "TtsStyleContextPromptContext",
    "build_tts_style_context_section",
]

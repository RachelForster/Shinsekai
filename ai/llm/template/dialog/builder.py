"""Assemble a reusable Composite tree for the default dialog system prompt."""

import json

from .catalogs import (
    MusicCatalogSection,
    ProfilesSection,
    SceneCatalogSection,
    SpritesSection,
)
from ..core import Section, TextSection
from .context import DialogTemplateContext
from .fields import FieldContractSection
from .requirements import RequirementsSection


def _json_string_content(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


class JsonExampleSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        translate = context.translate
        parts = [
            translate("json_head_top"),
            translate(
                "json_speech_line",
                example=_json_string_content(translate("json_speech_example")),
            ),
        ]
        if context.use_effect:
            parts.append(translate("json_line_effect"))
        if context.use_llm_translation:
            parts.append(
                translate(
                    "json_line_trans",
                    target_voice_name=_json_string_content(context.target_voice_name),
                )
            )
        parts.append(translate("json_foot"))
        return "".join(parts)


class ClosingSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        extra = (
            context.translate("closing_extra_bgm")
            if context.has_real_background
            else ""
        )
        return context.translate("closing", extra=extra)


def build_dialog_section() -> Section[DialogTemplateContext]:
    """Return an inspectable tree; no configuration or context is captured here."""
    return Section(
        "dialog.system",
        children=(
            TextSection(
                "preamble",
                priority=10,
                text=lambda context: context.translate("preamble", names=context.names),
            ),
            Section(
                "output",
                priority=20,
                children=(
                    JsonExampleSection("example", priority=10),
                    FieldContractSection("fields", priority=20),
                ),
            ),
            Section(
                "characters",
                priority=30,
                children=(
                    SpritesSection("sprites", priority=10),
                    ProfilesSection("profiles", priority=20),
                ),
            ),
            Section(
                "background",
                priority=40,
                children=(
                    SceneCatalogSection("scenes", priority=10),
                    MusicCatalogSection("music", priority=20),
                ),
            ),
            TextSection("tools", priority=50, text=lambda context: context.tools_block),
            RequirementsSection("requirements", priority=60),
            ClosingSection("closing", priority=70),
            TextSection(
                "json_reminder",
                priority=80,
                text=lambda context: f"{context.json_reminder}\n",
            ),
        ),
    )

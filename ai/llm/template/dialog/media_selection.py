"""Reconcile restored media instructions with the active runtime mode."""

from ..core import TextSection
from .context import DialogTemplateContext
from .sections.background import BackgroundSection
from .sections.character import build_sprite_catalog_section


def build_media_selection_section(
    context: DialogTemplateContext,
) -> TextSection[DialogTemplateContext]:
    field = "vibe" if context.uses_vibe else "sprite"
    return TextSection(
        "runtime_media_selection",
        separator="\n",
        text=(
            "The active runtime media-selection rules below supersede conflicting "
            "media instructions and examples in the saved conversation. "
            f"Use the `{field}` field for character, scene and music selection. "
            "Keep the existing story, dialogue, translation and other output rules."
        ),
        children=(
            TextSection("selection_rule", text=context.translate(f"r_{field}")),
            build_sprite_catalog_section(context),
            BackgroundSection(),
        ),
    )

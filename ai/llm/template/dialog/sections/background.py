"""Background scene and music catalogs."""

from dataclasses import dataclass

from ...core import Section, TextSection
from ..context import DialogTemplateContext


@dataclass(frozen=True)
class BackgroundSection(Section[DialogTemplateContext]):
    id: str = "background"

    def _resolve_children(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
        background = context.background
        available = context.has_real_background and bool(background)
        scenes = TextSection(
            "scenes",
            enabled=(
                not context.uses_vibe
                and available
                and bool(getattr(background, "sprites", None))
            ),
            text=lambda ctx: (
                ctx.translate("scene_block_header")
                + ctx.translate("scene_count", n=len(background.sprites))
                + f"{background.bg_tags}\n\n"
            ),
        )
        music = TextSection(
            "music",
            enabled=(
                not context.uses_vibe
                and available
                and bool(getattr(background, "bgm_list", None))
            ),
            text=lambda ctx: (
                ctx.translate("bgm_block_header")
                + ctx.translate("bgm_count", n=len(background.bgm_list))
                + f"{background.bgm_tags}\n\n"
            ),
        )
        return scenes, music, *self.children

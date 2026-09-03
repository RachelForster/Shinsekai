"""Background scene and music catalogs as one major dialog section."""

from dataclasses import dataclass

from ..core import Section, TextSection
from .context import DialogTemplateContext


@dataclass(frozen=True)
class BackgroundSection(Section[DialogTemplateContext]):
    id: str = "background"

    def render_content(self, context: DialogTemplateContext) -> str:
        background = context.background
        available = context.has_real_background and bool(background)
        scenes = TextSection(
            "scenes",
            enabled=available and bool(getattr(background, "sprites", None)),
            text=lambda ctx: (
                ctx.translate("scene_block_header")
                + ctx.translate("scene_count", n=len(background.sprites))
                + f"{background.bg_tags}\n\n"
            ),
        )
        music = TextSection(
            "music",
            enabled=available and bool(getattr(background, "bgm_list", None)),
            text=lambda ctx: (
                ctx.translate("bgm_block_header")
                + ctx.translate("bgm_count", n=len(background.bgm_list))
                + f"{background.bgm_tags}\n\n"
            ),
        )
        return Section(self.id, children=(scenes, music)).render(context)

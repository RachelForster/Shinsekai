"""Character and background context sections for dialog templates."""

from .dialog_context import DialogTemplateContext
from .section import Section


class SpritesSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        parts = [context.translate("sprites_header")]
        for name, character in context.characters:
            sprites = getattr(character, "sprites", None) or []
            parts.append(context.translate("sprites_count", name=name, n=len(sprites)))
            parts.append(f"{getattr(character, 'emotion_tags', '') or ''}\n\n")
        return "".join(parts)


class ProfilesSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        parts = [context.translate("profile_header")]
        for name, character in context.characters:
            setting = str(getattr(character, "character_setting", "") or "")
            if setting:
                parts.append(context.translate("profile_for", name=name))
                parts.append(f"{setting}\n\n")
        return "".join(parts)


class SceneCatalogSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        background = context.background
        if not context.has_real_background or not background or not background.sprites:
            return ""
        return (
            context.translate("scene_block_header")
            + context.translate("scene_count", n=len(background.sprites))
            + f"{background.bg_tags}\n\n"
        )


class MusicCatalogSection(Section[DialogTemplateContext]):
    def render_content(self, context: DialogTemplateContext) -> str:
        background = context.background
        if not context.has_real_background or not background or not background.bgm_list:
            return ""
        return (
            context.translate("bgm_block_header")
            + context.translate("bgm_count", n=len(background.bgm_list))
            + f"{background.bgm_tags}\n\n"
        )

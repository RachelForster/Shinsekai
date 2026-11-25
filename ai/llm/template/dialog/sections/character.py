"""Character sprite catalog and profiles."""

from dataclasses import dataclass
from typing import Any
from config.character_assets import get_character_assets
from config.schema import is_self_persona_name
from config.sprite_groups import (
    filter_sprite_indices_for_group,
    has_multiple_sprite_groups,
    resolve_default_sprite_group,
)
from core.media.asset_tags import tag_contents

from ...core import Section, TextSection
from ..context import DialogTemplateContext


def _character_sprite_catalog_text(
    context: DialogTemplateContext,
    name: str,
    character: Any,
) -> str:
    prompt_name = context.prompt_name_for(name, character)
    assets = get_character_assets(
        character, getattr(character, "avatar_type", "static")
    )
    if not has_multiple_sprite_groups(character):
        return (
            context.translate(
                "sprites_count",
                name=prompt_name,
                n=len(assets.sprites),
            )
            + f"{assets.emotion_tags}\n\n"
        )
    default_group = resolve_default_sprite_group(character)
    indices = filter_sprite_indices_for_group(character, default_group)
    tags = tag_contents(assets.emotion_tags, len(assets.sprites))
    filtered_tags = ", ".join(
        f"{idx + 1}:{tags[idx]}" if tags[idx] else f"{idx + 1}:"
        for idx in indices
        if 0 <= idx < len(assets.sprites)
    )
    return (
        context.translate(
            "sprites_count",
            name=prompt_name,
            n=len(indices),
        )
        + f"{filtered_tags}\n\n"
    )


def _profile_node(
    index: int, name: str, character: Any
) -> TextSection[DialogTemplateContext]:
    setting = str(getattr(character, "character_setting", "") or "")
    is_self = is_self_persona_name(name)

    def _render(context: DialogTemplateContext) -> str:
        prompt_name = context.prompt_name_for(name, character)
        if is_self:
            note = context.translate("self_persona_identity_note")
            body = f"{note}\n{setting}" if setting else note
        else:
            body = setting
        return context.translate("profile_for", name=prompt_name) + f"{body}\n\n"

    return TextSection(
        f"profile.{index}",
        enabled=bool(setting) or is_self,
        text=_render,
    )


def _brief_node(
    index: int, name: str, character: Any
) -> TextSection[DialogTemplateContext]:
    brief = str(getattr(character, "character_brief", "") or "").strip()
    setting = str(getattr(character, "character_setting", "") or "")
    content = brief or setting
    is_self = is_self_persona_name(name)

    def _render(context: DialogTemplateContext) -> str:
        prompt_name = context.prompt_name_for(name, character)
        if is_self:
            note = context.translate("self_persona_identity_note")
            body = f"{note}\n{content}" if content else note
        else:
            body = content
        return context.translate("brief_for", name=prompt_name) + f"{body}\n\n"

    return TextSection(
        f"brief.{index}",
        enabled=bool(content) or is_self,
        text=_render,
    )


@dataclass(frozen=True)
class CharacterSection(Section[DialogTemplateContext]):
    id: str = "characters"

    def _resolve_children(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
        primary_names = context.primary_character_names
        primary_characters = (
            context.characters
            if primary_names is None
            else tuple(
                (name, character)
                for name, character in context.characters
                if name in primary_names
            )
        )
        supporting_characters = (
            ()
            if primary_names is None
            else tuple(
                (name, character)
                for name, character in context.characters
                if name not in primary_names
            )
        )
        sprites = TextSection(
            "sprites",
            enabled=not context.uses_vibe,
            text=context.translate("sprites_header"),
            children=tuple(
                TextSection(
                    f"sprite.{index}",
                    text=_character_sprite_catalog_text(context, name, character),
                )
                for index, (name, character) in enumerate(context.characters)
            ),
        )
        profiles = TextSection(
            "profiles",
            text=context.translate("profile_header"),
            children=tuple(
                _profile_node(index, name, character)
                for index, (name, character) in enumerate(primary_characters)
            ),
        )
        briefs = TextSection(
            "briefs",
            enabled=bool(supporting_characters),
            text=context.translate("brief_header"),
            children=tuple(
                _brief_node(index, name, character)
                for index, (name, character) in enumerate(supporting_characters)
            ),
        )
        return sprites, profiles, briefs, *self.children

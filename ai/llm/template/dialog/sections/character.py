"""Character sprite catalog and profiles."""

from dataclasses import dataclass
from typing import Any
from config.character_assets import get_character_assets
from config.schema import is_self_persona
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
    assets = get_character_assets(
        character, getattr(character, "avatar_type", "static")
    )
    if not has_multiple_sprite_groups(character):
        return (
            context.translate(
                "sprites_count",
                name=name,
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
            name=name,
            n=len(indices),
        )
        + f"{filtered_tags}\n\n"
    )


def _with_self_persona_note(
    context: DialogTemplateContext,
    body: str,
    character: Any,
) -> str:
    if not is_self_persona(character):
        return body
    note = context.translate("self_persona_identity_note").strip()
    if not note:
        return body
    return f"{note}\n{body}" if body else note


def _profile_node(
    index: int, name: str, character: Any
) -> TextSection[DialogTemplateContext]:
    setting = str(getattr(character, "character_setting", "") or "")
    self_flagged = is_self_persona(character)
    return TextSection(
        f"profile.{index}",
        enabled=bool(setting) or self_flagged,
        text=lambda context: context.translate("profile_for", name=name)
        + _with_self_persona_note(context, setting, character)
        + "\n\n",
    )


def _brief_node(
    index: int, name: str, character: Any
) -> TextSection[DialogTemplateContext]:
    brief = str(getattr(character, "character_brief", "") or "").strip()
    setting = str(getattr(character, "character_setting", "") or "")
    content = brief or setting
    self_flagged = is_self_persona(character)
    return TextSection(
        f"brief.{index}",
        enabled=bool(content) or self_flagged,
        text=lambda context: context.translate("brief_for", name=name)
        + _with_self_persona_note(context, content, character)
        + "\n\n",
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
            enabled=context.include_character_profiles,
            text=context.translate("profile_header"),
            children=tuple(
                _profile_node(index, name, character)
                for index, (name, character) in enumerate(primary_characters)
            ),
        )
        briefs = TextSection(
            "briefs",
            enabled=context.include_character_profiles and bool(supporting_characters),
            text=context.translate("brief_header"),
            children=tuple(
                _brief_node(index, name, character)
                for index, (name, character) in enumerate(supporting_characters)
            ),
        )
        return sprites, profiles, briefs, *self.children

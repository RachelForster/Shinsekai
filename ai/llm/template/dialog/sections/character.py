"""Character sprite catalog and profiles."""

from dataclasses import dataclass
from typing import Any

from ...core import Section, TextSection
from ..context import DialogTemplateContext


def _profile_node(
    index: int, name: str, character: Any
) -> TextSection[DialogTemplateContext]:
    setting = str(getattr(character, "character_setting", "") or "")
    return TextSection(
        f"profile.{index}",
        enabled=bool(setting),
        text=lambda context: context.translate("profile_for", name=name)
        + f"{setting}\n\n",
    )


def _brief_node(
    index: int, name: str, character: Any
) -> TextSection[DialogTemplateContext]:
    brief = str(getattr(character, "character_brief", "") or "").strip()
    setting = str(getattr(character, "character_setting", "") or "")
    content = brief or setting
    return TextSection(
        f"brief.{index}",
        enabled=bool(content),
        text=lambda context: context.translate("brief_for", name=name)
        + f"{content}\n\n",
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
            text=context.translate("sprites_header"),
            children=tuple(
                TextSection(
                    f"sprite.{index}",
                    text=(
                        context.translate(
                            "sprites_count",
                            name=name,
                            n=len(getattr(character, "sprites", None) or []),
                        )
                        + f"{getattr(character, 'emotion_tags', '') or ''}\n\n"
                    ),
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

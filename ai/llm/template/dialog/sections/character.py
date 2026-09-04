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


@dataclass(frozen=True)
class CharacterSection(Section[DialogTemplateContext]):
    id: str = "characters"

    def children_for_context(
        self, context: DialogTemplateContext
    ) -> tuple[Section[DialogTemplateContext], ...]:
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
                for index, (name, character) in enumerate(context.characters)
            ),
        )
        return sprites, profiles, *self.children

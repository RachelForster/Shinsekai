"""Character sprite catalog and profiles as one major dialog section."""

from dataclasses import dataclass
from typing import Any

from ..core import Section, TextSection
from .context import DialogTemplateContext


def _profile_node(name: str, character: Any) -> TextSection[DialogTemplateContext]:
    setting = str(getattr(character, "character_setting", "") or "")
    return TextSection(
        name,
        enabled=bool(setting),
        text=lambda context: context.translate("profile_for", name=name)
        + f"{setting}\n\n",
    )


@dataclass(frozen=True)
class CharacterSection(Section[DialogTemplateContext]):
    id: str = "characters"

    def render_content(self, context: DialogTemplateContext) -> str:
        sprites = TextSection(
            "sprites",
            text=context.translate("sprites_header"),
            children=tuple(
                TextSection(
                    name,
                    text=(
                        context.translate(
                            "sprites_count",
                            name=name,
                            n=len(getattr(character, "sprites", None) or []),
                        )
                        + f"{getattr(character, 'emotion_tags', '') or ''}\n\n"
                    ),
                )
                for name, character in context.characters
            ),
        )
        profiles = TextSection(
            "profiles",
            text=context.translate("profile_header"),
            children=tuple(
                _profile_node(name, character) for name, character in context.characters
            ),
        )
        return Section(self.id, children=(sprites, profiles)).render(context)

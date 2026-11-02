"""Character sprite catalog and profiles."""

from dataclasses import dataclass
from typing import Any
from config.character_assets import get_character_assets

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
            enabled=not context.uses_vibe,
            text=context.translate("sprites_header"),
            children=tuple(
                TextSection(
                    f"sprite.{index}",
                    text=(
                        context.translate(
                            "sprites_count",
                            name=name,
                            n=len(get_character_assets(character, getattr(character, "avatar_type", "static")).sprites),
                        )
                        + f"{get_character_assets(character, getattr(character, 'avatar_type', 'static')).emotion_tags}\n\n"
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
        voice_tags = TextSection(
            "voice_tags",
            enabled=any(getattr(character, "scenarios", []) for _, character in context.characters),
            text=context.translate("voice_tags_header"),
            children=tuple(
                TextSection(
                    f"voice_tags.{index}",
                    text=context.translate("voice_tags_for", name=name, tags=" ".join(
                        f"[{scenario.get('name', '') if isinstance(scenario, dict) else scenario.name}]"
                        for scenario in getattr(character, "scenarios", [])
                    )),
                )
                for index, (name, character) in enumerate(context.characters)
                if getattr(character, "scenarios", [])
            ),
        )
        return sprites, profiles, briefs, *((voice_tags,) if voice_tags.enabled else ()), *self.children

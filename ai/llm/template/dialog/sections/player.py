"""Rules for a user-controlled cast member using the normal dialog schema."""

from dataclasses import dataclass

from ...core import Section
from ..context import DialogTemplateContext


@dataclass(frozen=True)
class PlayerSection(Section[DialogTemplateContext]):
    id: str = "player"

    def _render_self(self, context: DialogTemplateContext) -> str:
        name = str(context.player_name or "").strip()
        character = context.player_character
        if not name or character is None:
            return ""

        setting = str(getattr(character, "character_setting", "") or "").strip()
        if context.uses_vibe:
            portrait_field = "vibe"
            portrait_value = context.translate("player_portrait_vibe_value")
            speech_media = '"vibe":""'
        else:
            portrait_field = "sprite"
            portrait_value = "01"
            speech_media = '"sprite":"-1"'

        speech_contract = (
            context.translate(
                "player_speech_contract",
                name=name,
                speech_media=speech_media,
                target_voice_name=context.target_voice_name,
            )
            if context.read_player_speech
            else context.translate("player_speech_disabled", name=name)
        )
        return context.translate(
            "player_control",
            name=name,
            setting=setting,
            portrait_field=portrait_field,
            portrait_value=portrait_value,
            speech_contract=speech_contract,
        )

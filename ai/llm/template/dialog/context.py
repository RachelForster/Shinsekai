"""Inputs resolved once for a dialog system prompt."""

from dataclasses import dataclass, field
from typing import Any, Callable

from config.character_assets import get_character_assets
from config.schema import is_self_persona_name, resolve_character_prompt_name
from sdk.types import OutputContractPatch

from ai.llm.template.core.context import TemplateContext


@dataclass(frozen=True)
class EffectCatalogEntry:
    label: str
    kind: str
    modes: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class EffectCatalogContext(TemplateContext):
    """Catalog inputs supplied at launch, independently of template generation."""

    effects: tuple[EffectCatalogEntry, ...] = ()
    translate: Callable[[str], str] | None = None


@dataclass(frozen=True)
class DialogTemplateContext(TemplateContext):
    characters: tuple[tuple[str, Any], ...]
    translate: Callable[..., str]
    target_voice_name: str
    json_reminder: str
    player_name: str = ""
    player_character: Any = None
    self_persona_setting: str = ""
    self_persona_display_name: str = ""
    colliding_character_names: tuple[str, ...] = ()
    read_player_speech: bool = False
    allow_player_dialogue: bool = True
    effect_catalog: EffectCatalogContext | None = field(default=None, kw_only=True)
    primary_character_names: frozenset[str] | None = None
    tools_block: str = ""
    background: Any = None
    has_real_background: bool = False
    output_contract_patches: tuple[OutputContractPatch, ...] = ()
    use_effect: bool = False
    use_cg: bool = False
    use_llm_translation: bool = False
    use_cot: bool = False
    use_choice: bool = True
    use_narration: bool = True
    use_stat: bool = True
    max_speech_chars: int = 0
    max_dialog_items: int = 0
    media_selection_mode: str = "indexed"

    def _all_colliding_names(self) -> tuple[str, ...]:
        names = [name for name, _ in self.characters]
        if self.player_name:
            names.append(self.player_name)
        names.extend(self.colliding_character_names)
        return tuple(names)

    def prompt_name_for(self, canonical_name: str, character: Any = None) -> str:
        return resolve_character_prompt_name(
            character,
            canonical_name,
            colliding_names=self._all_colliding_names(),
        )

    @property
    def self_persona_display_prompt_name(self) -> str:
        for name, character in self.characters:
            if is_self_persona_name(name):
                resolved = self.prompt_name_for(name, character)
                return "" if is_self_persona_name(resolved) else resolved
        if is_self_persona_name(self.player_name) and self.player_character is not None:
            resolved = self.prompt_name_for(self.player_name, self.player_character)
            return "" if is_self_persona_name(resolved) else resolved
        candidate = str(self.self_persona_display_name or "").strip()
        if not candidate or is_self_persona_name(candidate):
            return ""
        collision_keys = {
            str(item or "").strip().casefold()
            for item in self._all_colliding_names()
            if str(item or "").strip() and not is_self_persona_name(item)
        }
        return "" if candidate.casefold() in collision_keys else candidate

    @property
    def names(self) -> str:
        return self.translate("name_sep").join(
            self.prompt_name_for(name, character) for name, character in self.characters
        )

    @property
    def uses_vibe(self) -> bool:
        return self.media_selection_mode == "semantic"

    @property
    def uses_full_sprite_ids(self) -> bool:
        return any(
            len(get_character_assets(character).sprites) > 99
            for _, character in self.characters
        )

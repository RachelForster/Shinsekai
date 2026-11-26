"""Inputs resolved once for a dialog system prompt."""

from dataclasses import dataclass, field
from typing import Any, Callable

from config.character_assets import get_character_assets
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID
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
    output_format_id: str = DEFAULT_DIALOG_FORMAT_ID

    @property
    def names(self) -> str:
        return self.translate("name_sep").join(name for name, _ in self.characters)

    @property
    def uses_vibe(self) -> bool:
        return self.media_selection_mode == "semantic"

    @property
    def uses_full_sprite_ids(self) -> bool:
        return any(
            len(get_character_assets(character).sprites) > 99
            for _, character in self.characters
        )

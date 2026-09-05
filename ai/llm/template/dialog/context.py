"""Inputs resolved once for a dialog system prompt."""

from dataclasses import dataclass
from typing import Any, Callable

from sdk.types import OutputContractPatch

from ..core import TemplateContext


@dataclass(frozen=True)
class DialogTemplateContext(TemplateContext):
    characters: tuple[tuple[str, Any], ...]
    translate: Callable[..., str]
    target_voice_name: str
    json_reminder: str
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

    @property
    def names(self) -> str:
        return self.translate("name_sep").join(name for name, _ in self.characters)

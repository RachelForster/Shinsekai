"""Pluggable LLM dialog output format contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sdk.messages import LLMDialogMessage
    from sdk.types import RequirementSpec

DEFAULT_DIALOG_FORMAT_ID = "json_v1"
XML_DIALOG_FORMAT_ID = "xml_v1"


@dataclass(frozen=True, slots=True)
class DialogFormatPromptContext:
    """Normalized template switches passed to dialog format prompt hooks."""

    locale: str = "zh_CN"
    media_field: str = "sprite"
    uses_vibe: bool = False
    uses_full_sprite_ids: bool = False
    has_real_background: bool = False
    use_cot: bool = False
    use_narration: bool = True
    use_choice: bool = True
    use_stat: bool = True
    use_cg: bool = False
    use_effect: bool = False
    use_llm_translation: bool = False
    target_voice_name: str = ""
    names: str = ""
    max_speech_chars: int = 0
    max_dialog_items: int = 0
    removed_optional_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DialogOutfitHintContext:
    """Inputs for format-specific runtime outfit-switch instructions."""

    locale: str = "zh_CN"
    media_selection_mode: str = "indexed"
    auto_switch_enabled: bool = True
    example_character: str = ""
    example_target_group: str = ""
    example_vibe: str = ""
    example_speech: str = ""


@dataclass(frozen=True, slots=True)
class DialogOutfitHint:
    """Localized outfit-switching rule and optional concrete example."""

    rule_text: str
    example_line: str = ""


@dataclass(frozen=True, slots=True)
class DialogPlayerHintContext:
    """Inputs for format-specific player-character control rules."""

    locale: str = "zh_CN"
    name: str = ""
    setting: str = ""
    uses_vibe: bool = False
    allow_player_dialogue: bool = True
    read_player_speech: bool = False
    target_voice_name: str = ""
    portrait_field: str = "sprite"
    portrait_value: str = "01"


@runtime_checkable
class DialogStreamParser(Protocol):
    """Stateful incremental parser emitting dialog items from streamed LLM chunks."""

    buffer: str
    accumulated_text: str
    parse_failures: int
    last_error: str

    @property
    def has_errors(self) -> bool: ...

    @property
    def unparsed_remainder(self) -> str: ...

    def feed(self, chunk: str) -> list["LLMDialogMessage"]: ...

    def flush(self) -> list["LLMDialogMessage"]: ...


class DialogOutputFormat(ABC):
    """Contract implemented by built-in and plugin-provided LLM dialog formats."""

    format_id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    api_response_format: ClassVar[dict[str, str] | None] = None

    @abstractmethod
    def create_stream_parser(self) -> DialogStreamParser:
        """Create a fresh stateful stream parser for a single LLM turn."""

    @abstractmethod
    def parse_complete(self, raw: str) -> list["LLMDialogMessage"]:
        """Parse a complete assistant response into ordered dialog items."""

    @abstractmethod
    def validate(self, raw: str) -> bool:
        """Return True when raw output satisfies this format's minimum valid contract."""

    def can_parse(self, raw: str) -> bool:
        """Heuristic probe for history auto-detection when no format tag is stored."""
        return self.validate(raw)

    def serialize(self, items: Sequence["LLMDialogMessage"]) -> str | None:
        """Optionally serialize dialog items back into this format for few-shot history."""
        return None

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None:
        """Optional prompt schema snippet for third-party or built-in plugin formats."""
        return None

    def render_requirements(
        self,
        prompt_context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None:
        """Optional structured requirement rules for template generation."""
        return None

    def render_outfit_hint(
        self,
        context: DialogOutfitHintContext,
    ) -> DialogOutfitHint | None:
        """Optional format-specific outfit-switching hint injected before chat turns."""
        return None

    def render_player_hint(
        self,
        context: DialogPlayerHintContext,
    ) -> str | None:
        """Optional format-specific player-character control instructions."""
        return None

    def render_format_reminder(self, *, locale: str) -> str | None:
        """Optional concise format reminder override for runtime injection."""
        return None

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None:
        """Optional format-repair instruction override on invalid output."""
        return None


@dataclass(frozen=True, slots=True)
class DialogFormatContribution:
    """Plugin-registered dialog output format entry."""

    format_id: str
    factory: Callable[[], DialogOutputFormat]
    label: str = ""
    priority: int = 100
    plugin_id: str = ""

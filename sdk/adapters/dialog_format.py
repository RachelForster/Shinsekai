"""Pluggable LLM dialog output format contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sdk.messages import LLMDialogMessage

DEFAULT_DIALOG_FORMAT_ID = "json_v1"
XML_DIALOG_FORMAT_ID = "xml_v1"


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
    ) -> str | None:
        """Optional prompt schema snippet for third-party plugin formats."""
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

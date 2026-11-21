"""Composite prompt nodes with stable ordering and explicit context flow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar, final

from .context import TemplateContext


ContextT = TypeVar("ContextT", bound=TemplateContext)


@dataclass(frozen=True)
class Section(Generic[ContextT]):
    """Render this node's content followed by its ordered child sections.

    Lower priorities render first; equal priorities retain insertion order.
    IDs are nonempty and unique among siblings. Empty output is omitted, but
    whitespace in nonempty output is preserved. ``render`` is the only public
    operation. Subclasses may implement ``_render_self`` for their own text and
    ``_resolve_children`` for context-dependent children. Disabled nodes skip
    both hooks and their entire subtree. The default composite has no own text.
    """

    id: str
    children: tuple[Section[ContextT], ...] = ()
    priority: float = 100.0
    separator: str = ""
    enabled: bool = field(default=True, kw_only=True)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("section id must not be empty")
        object.__setattr__(self, "children", tuple(self.children))
        ids = [child.id for child in self.children]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate child section id in {self.id!r}")

    def _render_self(self, context: ContextT) -> str:
        return ""

    def _resolve_children(self, context: ContextT) -> tuple[Section[ContextT], ...]:
        """Return context-dependent children; static composites use ``children``."""
        return self.children

    @final
    def render(self, context: ContextT) -> str:
        if not self.enabled:
            return ""
        parts = [self._render_self(context)]
        children = tuple(self._resolve_children(context))
        ids = [child.id for child in children]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate render-time child section id in {self.id!r}")
        parts.extend(
            child.render(context)
            for child in sorted(children, key=lambda child: child.priority)
        )
        return self.separator.join(part for part in parts if part)


@dataclass(frozen=True)
class TextSection(Section[ContextT]):
    """A literal or context-dependent text node; text is never format-expanded."""

    text: str | Callable[[ContextT], str] = ""

    def _render_self(self, context: ContextT) -> str:
        return self.text(context) if callable(self.text) else self.text


@dataclass(frozen=True)
class I18nSection(Section[ContextT]):
    """Section that renders a localized PromptCatalog key using context.tr."""

    key: str = field(default="", kw_only=True)
    params: Mapping[str, Any] | Callable[[ContextT], Mapping[str, Any]] = field(
        default_factory=dict,
        kw_only=True,
    )

    def _render_self(self, context: ContextT) -> str:
        if not self.key:
            return ""
        resolved = self.params(context) if callable(self.params) else self.params
        return context.tr(self.key, **dict(resolved))

"""Composite prompt nodes with stable ordering and explicit context flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from .context import TemplateContext


ContextT = TypeVar("ContextT", bound=TemplateContext)


@dataclass(frozen=True)
class Section(Generic[ContextT]):
    """Render this node's content followed by its ordered child sections.

    Lower priorities render first; equal priorities retain insertion order.
    IDs are nonempty and unique among siblings. Empty output is omitted, but
    whitespace in nonempty output is preserved. Override ``render_content``
    for a leaf or a composite heading, and ``context_for_children`` to scope
    context changes to a subtree. Disabled nodes skip their content, context
    hooks and entire subtree. The default composite has no own content.
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

    def render_content(self, context: ContextT) -> str:
        return ""

    def context_for_children(self, context: ContextT) -> ContextT:
        return context

    def render(self, context: ContextT) -> str:
        if not self.enabled:
            return ""
        parts = [self.render_content(context)]
        if self.children:
            child_context = self.context_for_children(context)
            parts.extend(
                child.render(child_context)
                for child in sorted(self.children, key=lambda child: child.priority)
            )
        return self.separator.join(part for part in parts if part)


@dataclass(frozen=True)
class TextSection(Section[ContextT]):
    """A literal or context-dependent text node; text is never format-expanded."""

    text: str | Callable[[ContextT], str] = ""

    def render_content(self, context: ContextT) -> str:
        return self.text(context) if callable(self.text) else self.text

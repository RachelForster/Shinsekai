"""One localized, feature-gated dialog requirement."""

from dataclasses import dataclass, field
from typing import Any

from ...core import Section
from ..context import DialogTemplateContext


@dataclass(frozen=True)
class RequirementSection(Section[DialogTemplateContext]):
    arguments: dict[str, Any] = field(default_factory=dict)
    resolved_text: str | None = None

    def requirement_text(self, context: DialogTemplateContext) -> str:
        """Resolve the rule text before its list-item presentation is applied."""
        if self.resolved_text is not None:
            return self.resolved_text
        return context.translate(self.id, **self.arguments)

    def render_content(self, context: DialogTemplateContext) -> str:
        return f"- {self.requirement_text(context)}\n"

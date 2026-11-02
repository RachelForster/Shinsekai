"""Selected audio and image effect catalogs for dialogue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai.llm.template.core.section import Section

if TYPE_CHECKING:
    from ai.llm.template.dialog.context import DialogTemplateContext
    from ai.llm.template.prompts.system import RuntimePromptContext


@dataclass(frozen=True)
class EffectCatalogSection(Section["DialogTemplateContext | RuntimePromptContext"]):
    id: str = "effects"

    def _render_self(self, context: DialogTemplateContext | RuntimePromptContext) -> str:
        catalog = context.effect_catalog
        if catalog is None or not catalog.effects:
            return ""
        if catalog.translate is None:
            raise ValueError("effect catalog requires a translator")
        translate = catalog.translate
        lines = [translate("effects_header").strip()]
        for entry in catalog.effects:
            kind = translate(f"effect_type_{entry.kind}")
            lines.append(f"- {entry.label} [{kind}; {', '.join(entry.modes)}]")
        return "\n" + "\n".join(lines)

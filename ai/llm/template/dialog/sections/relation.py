"""Render selected characters' relationship perspectives as concise text."""
from dataclasses import dataclass
import logging

from config.schema import RelationGraph

from ...core import Section
from ..context import DialogTemplateContext

logger = logging.getLogger(__name__)


def _clean(value):
    return " ".join(str(value).split())


def _normalize_name(value):
    return value.strip().casefold()


def _build_relation_context(characters, primary_names=None):
    selected = {_normalize_name(name) for name, _ in characters}
    blocks = []
    for name, character in characters:
        if primary_names is not None and name not in primary_names:
            continue
        try:
            graph = getattr(character, "relation_graph", None)
            if graph is None:
                continue
            graph = RelationGraph.model_validate(graph)
            edges = [edge for edge in graph.edges if (
                _normalize_name(edge.source) in selected
                or _normalize_name(edge.target) in selected
            ) and (edge.content.strip() or edge.temperature != 0)]
            edges.sort(key=lambda edge: (
                not (_normalize_name(edge.source) in selected and _normalize_name(edge.target) in selected),
                edge.source, edge.target,
            ))
            if edges:
                blocks.append((name, edges))
        except Exception:
            logger.exception("Character relationship retrieval unavailable for %s", name)
    return tuple(blocks)


@dataclass(frozen=True)
class RelationSection(Section[DialogTemplateContext]):
    id: str = "relations"

    def _render_self(self, context: DialogTemplateContext) -> str:
        blocks = _build_relation_context(context.characters, context.primary_character_names)
        rendered = []
        for owner, edges in blocks:
            heading = context.translate("relations_owner", name=_clean(owner))
            lines = []
            for edge in edges:
                line = context.translate(
                    "relations_edge",
                    source=_clean(edge.source),
                    target=_clean(edge.target),
                    content=_clean(edge.content),
                )
                if edge.temperature:
                    line += context.translate("relations_temperature", temperature=edge.temperature)
                lines.append(line)
            if lines:
                rendered.append(heading + "\n" + "\n".join(lines))
        if not rendered:
            return ""
        return context.translate("relations_header") + context.translate("relations_description") + "\n" + "\n".join(rendered) + "\n\n"

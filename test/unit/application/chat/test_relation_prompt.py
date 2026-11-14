"""Relationship prompt selection and rendering contracts."""
from types import SimpleNamespace

import pytest

from ai.llm.template.dialog.context import DialogTemplateContext
from ai.llm.template.dialog.sections.relation import RelationSection


def render(characters, primary=None):
    def translate(key, **values):
        templates = {
            "relations_header": "Relationships:\n",
            "relations_description": "Separate perspectives.\n",
            "relations_owner": "[{name}]",
            "relations_edge": "{source} to {target}: {content}",
            "relations_temperature": " (affinity: {temperature})",
        }
        return templates[key].format(**values)
    return RelationSection().render(DialogTemplateContext(
        characters=tuple(characters), translate=translate, target_voice_name="",
        json_reminder="", primary_character_names=primary,
    ))


def character(nodes, edges):
    return SimpleNamespace(relation_graph={"nodes": [{"key": name} for name in nodes], "edges": edges})


def edge(source, target, content="friend", temperature=0):
    return {"source": source, "target": target, "content": content, "temperature": temperature}


def test_prompt_includes_both_directions_and_excludes_unselected_relationships():
    graph = character(["A", "B", "C", "D"], [edge("A", "B"), edge("B", "A", "trust"), edge("C", "D")])
    text = render([("A", graph)])
    assert "A to B: friend" in text
    assert "B to A: trust" in text
    assert "C to D" not in text
    assert "D" not in text


def test_prompt_preserves_separate_owner_perspectives_and_primary_scope():
    first = character(["A", "B"], [edge("A", "B", "friend")])
    second = character(["A", "B"], [edge("A", "B", "rival")])
    text = render([("A", first), ("B", second)])
    assert "[A]\nA to B: friend" in text
    assert "[B]\nA to B: rival" in text
    assert "A to B: friend\n\n[B]" in text
    assert "[B]" not in render([("A", first), ("B", second)], frozenset({"A"}))
    assert render([("A", first)], frozenset()) == ""


def test_prompt_keeps_temperature_only_and_omits_empty_relationships():
    graph = character(["A", "B", "C"], [edge("A", "B", "", 4), edge("A", "C", "", 0)])
    text = render([("A", graph)])
    assert "A to B:  (affinity: 4)" in text
    assert "A to C" not in text


def test_prompt_empty_or_invalid_graph_is_omitted():
    assert render([("A", character(["A"], []))]) == ""
    assert render([("A", SimpleNamespace(relation_graph=None))]) == ""
    assert render([("A", SimpleNamespace(relation_graph={"edges": [edge("A", "B")]}))]) == ""


def test_prompt_includes_all_selected_relationships():
    names = ["A"] + [f"B{i}" for i in range(99)]
    graph = character(names, [edge("A", name, "x" * 100) for name in names[1:]])
    text = render([("A", graph)])
    lines = [line for line in text.splitlines() if line.startswith("A to ")]
    assert len(lines) == 99
    assert all(line.endswith("x" * 100) for line in lines)

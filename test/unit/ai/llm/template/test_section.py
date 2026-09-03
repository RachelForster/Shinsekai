from dataclasses import dataclass, replace

import pytest

from ai.llm.template import Section, TemplateContext, TextSection


@dataclass(frozen=True)
class GreetingContext(TemplateContext):
    name: str


class ScopedSection(Section[GreetingContext]):
    def context_for_children(self, context: GreetingContext) -> GreetingContext:
        return replace(context, name="local")


def test_nested_sections_order_siblings_stably_and_preserve_whitespace():
    prompt = Section(
        "system",
        separator="\n",
        children=(
            TextSection("last", priority=20, text=" end "),
            Section(
                "group",
                priority=10,
                separator="/",
                children=(
                    TextSection("b", text="B"),
                    TextSection("a", text="A"),
                    TextSection("empty", text=""),
                ),
            ),
            TextSection("first", priority=0, text="start"),
        ),
    )

    assert prompt.render(TemplateContext()) == "start\nB/A\n end "
    assert [child.id for child in prompt.children] == ["last", "group", "first"]


def test_context_is_inherited_and_subtree_override_does_not_leak():
    seen = []

    def greet(context: GreetingContext) -> str:
        seen.append(context)
        return context.name

    prompt = Section(
        "user",
        separator=",",
        children=(
            TextSection("before", text=greet),
            ScopedSection(
                "scope",
                children=(
                    Section("nested", children=(TextSection("greeting", text=greet),)),
                ),
            ),
            TextSection("after", text=greet),
        ),
    )
    context = GreetingContext("global")

    assert prompt.render(context) == "global,local,global"
    assert seen[0] is context and seen[2] is context
    assert context.name == "global"
    assert prompt.render(GreetingContext("next")) == "next,local,next"


def test_content_and_children_compose_without_interpreting_user_text():
    prompt = TextSection(
        "input",
        text="Context",
        separator="\n",
        children=(TextSection("text", text=lambda context: context.name),),
    )

    assert prompt.render(GreetingContext('{"raw": "{name}"}')) == (
        'Context\n{"raw": "{name}"}'
    )
    assert Section("empty").render(TemplateContext()) == ""


def test_section_copies_child_collection_and_rejects_ambiguous_ids():
    children = [TextSection("one", text="one")]
    section = Section("root", children=children)
    children.clear()
    assert section.render(TemplateContext()) == "one"
    with pytest.raises(ValueError, match="duplicate child"):
        Section("root", children=(TextSection("same"), TextSection("same")))
    with pytest.raises(ValueError, match="must not be empty"):
        Section(" ")


def test_disabled_node_skips_content_context_hooks_and_entire_subtree():
    class UnreachableSection(Section):
        def render_content(self, context):
            pytest.fail("disabled content must not run")

        def context_for_children(self, context):
            pytest.fail("disabled context hook must not run")

    disabled = UnreachableSection(
        "disabled",
        enabled=False,
        children=(UnreachableSection("nested"),),
    )
    context = TemplateContext()
    assert disabled.render(context) == ""
    assert (
        Section(
            "root",
            separator="|",
            children=(
                TextSection("before", text="before"),
                disabled,
                TextSection("after", text="after"),
            ),
        ).render(context)
        == "before|after"
    )


def test_enabled_is_keyword_only_and_can_be_toggled_without_mutating_the_node():
    node = TextSection("literal", (), 10, "", "text")
    assert node.enabled is True
    assert replace(node, enabled=False).render(TemplateContext()) == ""
    assert node.render(TemplateContext()) == "text"

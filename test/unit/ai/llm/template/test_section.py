from dataclasses import dataclass, replace

import pytest

from ai.llm.template import Section, TemplateContext, TextSection


@dataclass(frozen=True)
class GreetingContext(TemplateContext):
    name: str


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


def test_context_is_inherited_without_being_retained_between_renders():
    seen = []

    def greet(context: GreetingContext) -> str:
        seen.append(context)
        return context.name

    prompt = Section(
        "user",
        separator=",",
        children=(
            TextSection("before", text=greet),
            Section(
                "scope",
                children=(
                    Section("nested", children=(TextSection("greeting", text=greet),)),
                ),
            ),
            TextSection("after", text=greet),
        ),
    )
    context = GreetingContext("global")

    assert prompt.render(context) == "global,global,global"
    assert all(item is context for item in seen)
    assert context.name == "global"
    assert prompt.render(GreetingContext("next")) == "next,next,next"


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


def test_disabled_node_skips_both_rendering_hooks_and_entire_subtree():
    class UnreachableSection(Section):
        def _render_self(self, context):
            pytest.fail("disabled content must not run")

        def _resolve_children(self, context):
            pytest.fail("disabled children hook must not run")

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


def test_contextual_children_use_the_current_render_context():
    seen = []

    class DynamicSection(Section[GreetingContext]):
        def _resolve_children(self, context):
            seen.append(context)
            return (
                TextSection("dynamic", priority=20, text=context.name),
                *self.children,
            )

    node = DynamicSection(
        "dynamic_root",
        separator="|",
        children=(TextSection("extension", priority=10, text="extension"),),
    )

    assert node.render(GreetingContext("global")) == "extension|global"
    assert seen == [GreetingContext("global")]


def test_contextual_children_reject_duplicate_ids_at_render_time():
    class DuplicateSection(Section):
        def _resolve_children(self, context):
            return TextSection("same"), TextSection("same")

    with pytest.raises(ValueError, match="duplicate render-time child"):
        DuplicateSection("root").render(TemplateContext())

"""Golden outputs captured before moving the application's prompt renderers."""

import ast
import json
from copy import deepcopy
from pathlib import Path

import pytest

import ai.llm.template.story as story_templates
from ai.llm.template.core import TemplateContext
from ai.llm.template.story import (
    AUTHOR_COMPILER_TEMPLATE,
    StoryGuidanceContext,
    StoryGuidanceTransition,
    StoryRequestContext,
    build_story_assessment_system_section,
    build_story_assessment_user_section,
    build_story_author_system_section,
    build_story_author_user_section,
    build_story_guidance_section,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/story_prompts.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FIXTURE["guidance"])
def test_guidance_preserves_existing_output(case):
    data = dict(case["context"])
    data["transitions"] = tuple(
        StoryGuidanceTransition(**item) for item in data["transitions"]
    )
    assert (
        build_story_guidance_section().render(StoryGuidanceContext(**data))
        == case["expected"]
    )


def test_system_prompts_preserve_existing_instructions():
    assert (
        build_story_author_system_section().render(TemplateContext(locale="en"))
        == FIXTURE["authorSystem"]
    )
    assert AUTHOR_COMPILER_TEMPLATE == FIXTURE["authorSystem"]
    assert (
        build_story_assessment_system_section().render(TemplateContext())
        == FIXTURE["assessmentSystem"]
    )


@pytest.mark.parametrize("case", FIXTURE["authorRequests"])
def test_author_requests_preserve_compact_json_for_generation_and_repair(case):
    payload = deepcopy(case["payload"])
    rendered = build_story_author_user_section().render(StoryRequestContext(payload))
    assert rendered == case["expected"]
    assert json.loads(rendered) == payload == case["payload"]


def test_assessment_request_preserves_json_spacing_and_data():
    case = FIXTURE["assessmentRequest"]
    payload = deepcopy(case["payload"])
    assert (
        build_story_assessment_user_section().render(StoryRequestContext(payload))
        == case["expected"]
    )
    assert payload == case["payload"]


def test_guidance_section_can_render_new_states_without_retaining_previous_values():
    section = build_story_guidance_section()
    first = StoryGuidanceContext("A", "first", 1, 3, background="背景")
    second = StoryGuidanceContext("B", "next", 0, None)
    section.render(first)
    rendered = section.render(second)
    assert "背景" not in rendered.split("\n")[-1]
    assert json.loads(rendered.split("\n")[-1]) == {
        "当前剧情": "B",
        "剧情要求": "next",
        "已进行轮数": 0,
        "建议轮数": None,
        "剧情衔接条件": [],
    }


def test_story_templates_do_not_depend_on_session_or_application_services():
    directory = Path(story_templates.__file__).parent
    for path in directory.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module or ""]
            assert not any(
                module.split(".")[0]
                in {"application", "core", "config", "frontend_bridge_core"}
                for module in modules
            ), path


@pytest.mark.parametrize(
    ("locale", "author_marker", "assessment_marker", "guidance_marker", "title_key"),
    [
        ("zh_CN", "Shinsekai 的剧情编译作者", "你只判断已发生的对话", "【当前剧本进度】", "当前剧情"),
        ("en", "Shinsekai's story compiler author", "You only determine whether", "[Current Story Progress]", "current_node"),
        ("ja", "Shinsekai のストーリーコンパイラ作者", "あなたはこれまでの会話が", "【現在のシナリオ進行】", "現在の展開"),
    ],
)
def test_story_prompts_switch_across_supported_locales(
    locale,
    author_marker,
    assessment_marker,
    guidance_marker,
    title_key,
):
    ctx = TemplateContext(locale=locale)
    author_text = build_story_author_system_section().render(ctx)
    assessment_text = build_story_assessment_system_section().render(ctx)
    guidance_text = build_story_guidance_section().render(
        StoryGuidanceContext(
            "Gate",
            "Investigate",
            1,
            3,
            transitions=(StoryGuidanceTransition("Enter", "Hall"),),
            background="Old Building",
            locale=locale,
        )
    )
    assert author_marker in author_text
    assert "responseSchema" in author_text
    assert assessment_marker in assessment_text
    assert '{"nextNodeId": null}' in assessment_text
    assert guidance_marker in guidance_text
    parsed_state = json.loads(guidance_text.split("\n")[-1])
    assert parsed_state[title_key] == "Gate"

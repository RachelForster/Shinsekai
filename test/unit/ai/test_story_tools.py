from __future__ import annotations

import json

from ai.tools.story_tools import (
    STORY_TOOL_GROUP,
    apply_semantic_signal,
    ensure_story_tools_registered,
    openai_tools_from_protocol,
    perform_intent,
    request_character_entry,
)
from ai.tools.tool_manager import ToolManager


def _reset_tm() -> ToolManager:
    manager = ToolManager()
    manager._tools_definitions.clear()
    manager._functions.clear()
    manager._tool_groups.clear()
    manager._tool_risks.clear()
    return manager


def test_story_tools_register_under_story_group_and_reject_direct_execution() -> None:
    manager = ensure_story_tools_registered(_reset_tm())
    names = {
        item["function"]["name"]
        for item in manager.get_definitions(groups=STORY_TOOL_GROUP)
    }
    assert names == {
        "perform_intent",
        "apply_semantic_signal",
        "request_character_entry",
        "request_character_exit",
        "request_character_replace",
    }
    assert manager.get_definitions() == []
    assert manager.search_tools("perform_intent") == []
    assert "story" not in manager.get_groups()

    result = json.loads(
        manager.execute(
            "perform_intent",
            json.dumps(
                {
                    "intentId": "reassure-ling",
                    "expectedNodeId": "old-school-gate",
                    "expectedRevision": 2,
                }
            ),
        )
    )
    assert result["ok"] is False
    assert result["errorCode"] == "scene.tool_not_executable"
    assert perform_intent("reassure-ling", "old-school-gate", 2)["ok"] is False
    assert apply_semantic_signal(
        "respect-boundary", "medium", 0.9, "endorsement", "old-school-gate", 2
    )["ok"] is False
    assert request_character_entry(
        "witness", "door-opened", "old-school-gate", 2
    )["ok"] is False


def test_openai_tools_bind_turn_allowlists_as_enums() -> None:
    manager = ensure_story_tools_registered(_reset_tm())
    tools = openai_tools_from_protocol(
        (
            {
                "name": "perform_intent",
                "allowedIntentIds": ["reassure-ling"],
                "expectedNodeId": "old-school-gate",
                "expectedRevision": 2,
            },
            {
                "name": "apply_semantic_signal",
                "allowedSignalIds": ["respect-boundary"],
                "strengths": ["weak", "medium", "strong"],
                "speechActs": ["endorsement"],
                "expectedNodeId": "old-school-gate",
                "expectedRevision": 2,
            },
        ),
        tool_manager=manager,
    )

    by_name = {item["function"]["name"]: item for item in tools}
    intent_props = by_name["perform_intent"]["function"]["parameters"]["properties"]
    assert intent_props["intentId"]["enum"] == ["reassure-ling"]
    assert intent_props["expectedNodeId"]["enum"] == ["old-school-gate"]
    assert intent_props["expectedRevision"]["enum"] == [2]
    signal_props = by_name["apply_semantic_signal"]["function"]["parameters"]["properties"]
    assert signal_props["signalId"]["enum"] == ["respect-boundary"]
    assert signal_props["strength"]["enum"] == ["weak", "medium", "strong"]
    assert openai_tools_from_protocol((), tool_manager=manager) == []

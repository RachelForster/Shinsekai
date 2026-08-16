from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import hashlib
import json

import pytest

from application.story import (
    CharacterResourceManager,
    CharacterSourceResolver,
    ConfigSceneModel,
    SceneOrchestrator,
    StoryCastApplicationService,
    StorySession,
    StoryTurnCancelledError,
    ValidatedCastPlanner,
)
from application.story.prompt import (
    compose_story_chat_system_prompt,
    compose_story_system_prompt,
    compose_story_user_message,
    compose_story_user_scene_context,
)
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from core.story import (
    SelectChoice,
    StoryCompiler,
    StoryRuntime,
    canonical_json,
    parse_story_project,
)
from test.unit.core.story.story_fixtures import campus_mystery_source


def _flags() -> FeatureFlagConfigManager:
    return FeatureFlagConfigManager(
        environ={},
        overrides={FeatureFlag.STORY_SYSTEM: True},
    )


def _library_payload(character_id: str) -> dict:
    return {
        "name": character_id.title(),
        "characterSetting": f"Actor profile for {character_id}",
        "sprites": [{"path": f"data/sprite/{character_id}.png"}],
        "toolPermissions": ["memory.search"],
    }


def _library_digest(character_id: str) -> str:
    payload = _library_payload(character_id)
    return (
        "sha256:"
        f"{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"
    )


class _Library:
    def load_character(self, character_id: str, revision: str | None):
        payload = _library_payload(character_id)
        digest = _library_digest(character_id)
        if revision and revision != digest:
            raise ValueError(f"unexpected pin {revision}")
        return {**payload, "_content_digest": digest, "_revision": digest}


class _Model:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def complete(self, request):
        self.requests.append(json.loads(json.dumps(request, ensure_ascii=False)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _story(*, model_responses):
    flags = _flags()
    source = deepcopy(campus_mystery_source())
    source["cast"]["characters"][0]["source"]["revision"] = _library_digest("ling")
    source["cast"]["characters"].append(
        {
            "id": "witness",
            "source": {
                "type": "local-library",
                "characterId": "witness",
                "revision": _library_digest("witness"),
            },
            "roles": ["witness"],
        }
    )
    source["cast"]["characters"][1]["source"] = {
        "type": "local-library",
        "characterId": "detective-zhou",
        "revision": _library_digest("detective-zhou"),
    }
    gate = source["narrativeGraph"]["nodes"][1]
    gate["castPolicy"] = {
        "mode": "fixed",
        "required": ["ling", "detective-zhou"],
        "constraints": {"minActive": 2, "maxActive": 3},
        "fallback": {"onLoadFailure": "error"},
    }
    gate["exposedContext"] = {
        "publicClue": "rain",
        "characterEntryReasonIds": ["door-opened"],
    }
    gate["lockedContext"] = {"secretCulprit": "headmaster-secret"}
    program = StoryCompiler().compile(parse_story_project(source))
    resources = CharacterResourceManager(
        flags,
        registry=program.character_registry,
        resolver=CharacterSourceResolver(
            flags,
            story_id=program.story_id,
            story_root=".",
            local_library=_Library(),
        ),
    )
    cast_service = StoryCastApplicationService(flags, resources)
    session = StorySession.create(
        StoryRuntime(program),
        flags,
        command_id="start",
        cast_plan_preparer=cast_service.prepare,
        cast_plan_committed=cast_service.committed,
    )
    session.execute(
        SelectChoice(
            "choice",
            1,
            "prepare-investigation",
            "transfer-day",
        )
    )
    model = _Model(*model_responses)
    orchestrator = SceneOrchestrator(
        flags,
        program=program,
        session=session,
        cast_service=cast_service,
        model=model,
    )
    return program, session, cast_service, model, orchestrator


def _intent_tool(*, revision: int = 2):
    return {
        "toolCalls": [
            {
                "id": "intent-1",
                "name": "perform_intent",
                "arguments": {
                    "intentId": "reassure-ling",
                    "expectedNodeId": "old-school-gate",
                    "expectedRevision": revision,
                },
            }
        ]
    }


def test_free_text_intent_is_adjudicated_before_dialogue_and_hides_secrets() -> None:
    _, session, _, model, scene = _story(
        model_responses=(
            _intent_tool(),
            {"dialogue": [{"characterId": "ling", "text": "谢谢你。"}]},
        )
    )

    result = scene.handle_free_text(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )

    assert session.active_branch.state.variables["trust.ling"] == 15
    assert result.dialogue[0].character_id == "ling"
    assert "headmaster-secret" not in json.dumps(model.requests, ensure_ascii=False)
    assert model.requests[0]["scene"]["publicContext"]["publicClue"] == "rain"
    tool_names = [item["name"] for item in model.requests[0]["tools"]]
    assert tool_names == [
        "perform_intent",
        "apply_semantic_signal",
        "request_character_entry",
    ]
    assert "allowedIntentIds" in model.requests[0]["tools"][0]
    assert "type" not in model.requests[0]["tools"][0]


def test_semantic_signal_uses_published_id_and_application_owned_fingerprint() -> None:
    signal_tool = {
        "toolCalls": [
            {
                "id": "signal-1",
                "name": "apply_semantic_signal",
                "arguments": {
                    "signalId": "respect-boundary",
                    "strength": "medium",
                    "confidence": 0.95,
                    "speechAct": "endorsement",
                    "fingerprint": "model-controlled-value",
                    "expectedNodeId": "old-school-gate",
                    "expectedRevision": 2,
                },
            }
        ]
    }
    _, session, _, model, scene = _story(
        model_responses=(
            signal_tool,
            {"dialogue": [{"characterId": "ling", "text": "我明白了。"}]},
        )
    )

    result = scene.handle_free_text(
        "我尊重你的决定",
        command_id="turn-1",
        message_id="message-1",
    )

    assert session.active_branch.state.variables["trust.ling"] == 12
    assert result.tool_results[0]["ok"] is True
    fingerprints = session.active_branch.state.semantic_signal_state.recent_fingerprints
    assert all("model-controlled-value" not in item[0] for item in fingerprints)


def test_duplicate_tool_call_and_dialogue_repair_do_not_repeat_effects() -> None:
    _, session, _, model, scene = _story(
        model_responses=(
            _intent_tool(),
            _intent_tool(),
            {"dialogue": [{"characterId": "invented", "text": "Nope"}]},
            {"dialogue": [{"characterId": "ling", "text": "修复后的对白"}]},
        )
    )

    result = scene.handle_free_text(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )

    assert session.active_branch.state.variables["trust.ling"] == 15
    assert session.active_branch.state.revision == 3
    assert result.dialogue[0].text == "修复后的对白"
    assert result.tool_results[1]["duplicate"] is True
    repeated = scene.handle_free_text(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )
    assert repeated.duplicate is True
    assert repeated.dialogue[0].text == result.dialogue[0].text
    assert session.active_branch.state.variables["trust.ling"] == 15
    assert len(model.requests) == 4


def test_character_entry_updates_allowlist_before_final_dialogue() -> None:
    entry_tool = {
        "toolCalls": [
            {
                "id": "entry-1",
                "name": "request_character_entry",
                "arguments": {
                    "characterId": "witness",
                    "reasonId": "door-opened",
                    "expectedNodeId": "old-school-gate",
                    "expectedRevision": 2,
                },
            }
        ]
    }
    _, session, resources, model, scene = _story(
        model_responses=(
            entry_tool,
            {"dialogue": [{"characterId": "witness", "text": "我看见了。"}]},
        )
    )

    result = scene.handle_free_text(
        "请目击者进来",
        command_id="turn-1",
        message_id="message-1",
    )

    assert "witness" in session.active_branch.state.cast_state.active_character_ids
    assert "witness" in resources.resources.actor_context().speaker_allowlist
    assert "witness" in model.requests[1]["actorContext"]["speakerAllowlist"]
    assert result.dialogue[0].character_id == "witness"


def test_model_timeout_degrades_without_mutating_story_state() -> None:
    _, session, _, _, scene = _story(model_responses=(TimeoutError("slow"),))
    before = session.active_branch.state

    result = scene.handle_free_text(
        "继续",
        command_id="turn-1",
        message_id="message-1",
    )

    assert result.degraded is True
    assert result.dialogue[0].character_id == "NARR"
    assert session.active_branch.state == before


def test_cast_planner_validates_candidate_envelope() -> None:
    planner = ValidatedCastPlanner(_flags())

    assert planner.validate(
        ["witness"],
        candidate_ids=["witness", "doctor"],
        required_ids=["ling"],
        maximum_active=2,
    ) == ("ling", "witness")
    with pytest.raises(ValueError):
        planner.validate(
            ["invented"],
            candidate_ids=["witness"],
            maximum_active=2,
        )


def test_config_scene_model_maps_native_tool_calls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class OpenAIAdapter:
        def chat(self, messages, stream=False, **kwargs):
            captured["tools"] = kwargs.get("tools")
            captured["messages"] = messages
            function = SimpleNamespace(
                name="perform_intent",
                arguments=json.dumps(
                    {
                        "intentId": "reassure-ling",
                        "expectedNodeId": "old-school-gate",
                        "expectedRevision": 2,
                    }
                ),
            )
            tool_call = SimpleNamespace(id="intent-1", function=function)
            message = SimpleNamespace(content="", tool_calls=[tool_call])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    manager = SimpleNamespace(
        llm_adapter=OpenAIAdapter(),
        chat=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("native tool adapters must not use the JSON chat path")
        ),
    )
    model = ConfigSceneModel(_flags(), config_manager=SimpleNamespace())
    monkeypatch.setattr(model, "_llm_manager", lambda: manager)

    result = model.complete(
        {
            "scene": {
                "nodeTitle": "旧校舍门口",
                "nodeId": "old-school-gate",
                "publicContext": {"publicClue": "rain"},
                "completedNodeIds": ["transfer-day"],
                "canon": ["转学第一天"],
                "userInput": {"text": "我会陪着你", "messageId": "m1"},
            },
            "actorContext": {
                "speakerAllowlist": ["ling", "NARR"],
                "characters": [
                    {
                        "id": "ling",
                        "name": "绫",
                        "setting": "转学生",
                        "sprites": [{"id": "01", "label": "微笑"}],
                    }
                ],
            },
            "tools": [
                {
                    "name": "perform_intent",
                    "allowedIntentIds": ["reassure-ling"],
                    "expectedNodeId": "old-school-gate",
                    "expectedRevision": 2,
                }
            ],
        }
    )

    assert result["toolCalls"][0]["name"] == "perform_intent"
    assert result["toolCalls"][0]["arguments"]["intentId"] == "reassure-ling"
    native_tools = captured["tools"]
    assert isinstance(native_tools, list)
    assert native_tools[0]["type"] == "function"
    assert native_tools[0]["function"]["name"] == "perform_intent"
    intent_enum = native_tools[0]["function"]["parameters"]["properties"]["intentId"][
        "enum"
    ]
    assert intent_enum == ["reassure-ling"]
    system = captured["messages"][0]["content"]
    user = captured["messages"][1]["content"]
    assert captured["messages"][0]["role"] == "system"
    assert "character_name" in system
    assert '"dialog"' in system
    assert "绫" in system
    assert "perform_intent" in system
    assert "shinsekai.scene.v1" not in system
    assert "我会陪着你" in user
    assert "shinsekai.scene.v1" not in user


def test_config_scene_model_keeps_json_fallback_without_native_tools(
    monkeypatch,
) -> None:
    class OtherAdapter:
        def chat(self, messages, stream=False, **kwargs):
            assert "tools" not in kwargs
            assert "response_format" not in kwargs
            return {
                "dialog": [
                    {
                        "character_name": "ling",
                        "speech": "好。",
                        "sprite": "01",
                    }
                ]
            }

    manager = SimpleNamespace(llm_adapter=OtherAdapter())
    model = ConfigSceneModel(_flags(), config_manager=SimpleNamespace())
    monkeypatch.setattr(model, "_llm_manager", lambda: manager)

    result = model.complete({"tools": []})
    assert result["dialog"][0]["character_name"] == "ling"


def test_free_mode_dialog_json_is_accepted_as_scene_dialogue() -> None:
    _, session, _, model, scene = _story(
        model_responses=(
            {
                "dialog": [
                    {
                        "character_name": "Ling",
                        "speech": "谢谢你。",
                        "sprite": "01",
                    }
                ]
            },
        )
    )

    result = scene.handle_free_text(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )

    assert result.dialogue[0].character_id == "ling"
    assert result.dialogue[0].display_name == "Ling"
    assert result.dialogue[0].text == "谢谢你。"
    assert result.dialogue[0].sprite == "01"
    assert result.dialogue[0].sprite_path
    assert "headmaster-secret" not in json.dumps(model.requests, ensure_ascii=False)


def test_scene_turn_is_persisted_per_branch_and_not_replayed() -> None:
    _, session, cast_service, model, scene = _story(
        model_responses=(
            {"dialogue": [{"characterId": "ling", "text": "谢谢你。"}]},
        )
    )
    first = scene.handle_free_text(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )
    recovered = SceneOrchestrator(
        _flags(),
        program=scene.program,
        session=session,
        cast_service=cast_service,
        model=_Model(),
    )

    second = recovered.handle_free_text(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )

    assert second.duplicate is True
    assert second.dialogue[0].text == first.dialogue[0].text
    assert len(model.requests) == 1


def test_scene_turn_cancels_when_another_request_forks() -> None:
    _, session, _, model, scene = _story(
        model_responses=({"dialogue": [{"characterId": "ling", "text": "晚到"}]},)
    )
    original = model.complete

    def forking(request):
        session.fork("alt")
        return original(request)

    model.complete = forking
    with pytest.raises(StoryTurnCancelledError):
        scene.handle_free_text(
            "我会陪着你",
            command_id="turn-1",
            message_id="message-1",
        )


def test_character_entry_tool_only_lists_optional_candidates() -> None:
    _, _, _, model, scene = _story(
        model_responses=({"dialogue": [{"characterId": "ling", "text": "好。"}]},)
    )

    scene.handle_free_text("继续", command_id="turn-1", message_id="message-1")

    entry = next(
        item
        for item in model.requests[0]["tools"]
        if item["name"] == "request_character_entry"
    )
    assert entry["allowedCharacterIds"] == ["witness"]
    assert "ling" not in entry["allowedCharacterIds"]


def test_story_system_prompt_uses_six_sections_and_free_mode_contract() -> None:
    from i18n import tr

    prompt = compose_story_system_prompt(
        {
            "scene": {
                "nodeTitle": "旧校舍门口",
                "nodeId": "old-school-gate",
                "publicContext": {"publicClue": "rain"},
                "completedNodeIds": ["transfer-day"],
                "canon": ["转学第一天"],
                "visibleVariables": {"trust.ling": 10},
                "userInput": {"text": "我会陪着你"},
            },
            "actorContext": {
                "characters": [
                    {
                        "id": "ling",
                        "name": "绫",
                        "setting": "转学生",
                        "sprites": [{"id": "01", "label": "微笑"}],
                    }
                ]
            },
            "tools": [
                {
                    "name": "perform_intent",
                    "allowedIntentIds": ["reassure-ling"],
                }
            ],
        }
    )
    user = compose_story_user_message(
        {
            "scene": {"userInput": {"text": "我会陪着你"}},
            "toolResults": [{"name": "perform_intent", "ok": True, "revision": 3}],
        }
    )

    for key in (
        "section_current",
        "section_progress",
        "section_format",
        "section_characters",
        "section_tools",
        "section_workflow",
    ):
        assert tr(f"story_scene_prompt.{key}") in prompt
    assert "旧校舍门口" in prompt
    assert "transfer-day" in prompt
    assert "character_name" in prompt
    assert '"dialog"' in prompt
    assert "绫" in prompt
    assert "微笑" in prompt
    assert "perform_intent" in prompt
    assert "headmaster-secret" not in prompt
    assert "shinsekai.scene.v1" not in prompt
    assert "我会陪着你" in user
    assert "perform_intent" in user
    assert "shinsekai.scene.v1" not in user
    user_scene = compose_story_user_scene_context(
        {
            "scene": {
                "nodeTitle": "旧校舍门口",
                "nodeId": "old-school-gate",
                "completedNodeIds": ["transfer-day"],
            }
        }
    )
    chat_system = compose_story_chat_system_prompt(
        {
            "scene": {"nodeTitle": "旧校舍门口"},
            "actorContext": {"characters": [{"id": "ling", "name": "绫"}]},
            "tools": [{"name": "perform_intent"}],
        }
    )
    assert tr("story_scene_prompt.section_current") in user_scene
    assert tr("story_scene_prompt.section_progress") in user_scene
    assert tr("story_scene_prompt.section_format") not in user_scene
    assert tr("story_scene_prompt.section_current") not in chat_system
    assert tr("story_scene_prompt.section_format") in chat_system


def test_story_prompt_treats_user_as_player_not_npc() -> None:
    from i18n import tr

    prompt = compose_story_system_prompt(
        {
            "scene": {"nodeTitle": "酒吧", "nodeId": "node1"},
            "actorContext": {
                "characters": [
                    {
                        "id": "fangshiyangming",
                        "name": "房石阳明",
                        "setting": "酒吧客人",
                        "sprites": [{"id": "01", "label": "微笑"}],
                    },
                    {
                        "id": "user",
                        "name": "用户",
                        "isPlayer": True,
                        "setting": "正在游玩的人",
                    },
                ]
            },
            "tools": [],
        }
    )

    assert "房石阳明" in prompt
    assert "用户" in prompt
    assert tr("story_scene_prompt.player_character") in prompt
    names_line = next(
        line
        for line in prompt.splitlines()
        if "character_name" in line and "房石阳明" in line
    )
    assert "用户" not in names_line


def test_prepare_llm_turn_appends_scene_prompt_without_calling_the_model() -> None:
    _, _session, _, model, scene = _story(model_responses=())

    turn = scene.prepare_llm_turn(
        "我会陪着你",
        command_id="turn-1",
        message_id="message-1",
    )

    from i18n import tr

    assert model.requests == []
    assert turn.user_context
    assert tr("story_scene_prompt.player_input_header") not in turn.user_context
    assert "old-school-gate" in turn.user_context or turn.node_id == "old-school-gate"
    assert "character_name" in turn.system_prompt
    assert '"dialog"' in turn.system_prompt

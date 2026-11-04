import pytest

from application.characters.generate_mmd_motion import _local_plan, _plan_from_prompt
from core.media.avatar.mmd_generated_motion import MotionPlan
from test.mocks import MockLLMAdapter


class _Config:
    def get_llm_api_config(self):
        return "provider", "model", "https://example.invalid", "secret"

    def merged_llm_factory_kwargs(self, provider, values):
        return values


def test_motion_agent_uses_one_no_tools_call_and_strict_local_plan(monkeypatch):
    from ai.llm import llm_manager

    calls = []

    class Factory:
        @staticmethod
        def create_adapter(**kwargs):
            assert kwargs["model"] == "model"
            return object()

    class Manager:
        def __init__(self, *, adapter, user_template, tools_enabled):
            assert "Available actions: nod, bow" in user_template
            assert tools_enabled is False

        def chat(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return '{"action":"nod","intensity":0.5,"duration_frames":60}'

    monkeypatch.setattr(llm_manager, "LLMAdapterFactory", Factory)
    monkeypatch.setattr(llm_manager, "LLMManager", Manager)
    assert _plan_from_prompt(_Config(), "nod gently", ["nod", "bow"]) == MotionPlan("nod", .5, 60)
    assert calls == [("nod gently", {
        "stream": False, "response_format": {"type": "text"}, "include_local_time": False,
    })]


def test_motion_agent_still_classifies_with_llm_without_offering_tools(monkeypatch):
    from ai.llm import llm_manager

    adapter = MockLLMAdapter(responses=['{"action":"wave","expression":"smile",'
                                        '"intensity":0.7,"duration_frames":75}'])
    monkeypatch.setattr(llm_manager.LLMAdapterFactory, "create_adapter", lambda **kwargs: adapter)

    plan = _plan_from_prompt(_Config(), "wave goodbye with a smile", ["wave"], ["smile"])

    assert plan == MotionPlan("wave", .7, 75, "smile")
    assert len(adapter.call_history) == 1
    assert adapter.call_history[0]["kwargs"]["tools"] is None


def test_motion_agent_rejects_action_outside_model_capability(monkeypatch):
    from ai.llm import llm_manager

    monkeypatch.setattr(llm_manager.LLMAdapterFactory, "create_adapter", lambda **kwargs: object())
    monkeypatch.setattr(llm_manager, "LLMManager", lambda **kwargs: type("Manager", (), {
        "chat": lambda self, prompt, **options: '{"action":"wave","intensity":0.5,"duration_frames":60}',
    })())
    with pytest.raises(ValueError, match="not supported"):
        _plan_from_prompt(_Config(), "wave", ["nod"])


def test_motion_agent_requires_llm_configuration():
    class Empty(_Config):
        def get_llm_api_config(self):
            return "", "", "", ""

    with pytest.raises(ValueError, match="incomplete"):
        _plan_from_prompt(Empty(), "nod", ["nod"])


@pytest.mark.parametrize("prompt,action,frames", [
    ("微笑三秒", "smile", 90),
    ("生气地握拳", "anger", 90),
    ("疑惑地歪头", "confusion", 90),
    ("轻轻挥手2秒", "wave", 60),
    ("请摇头", "shake_head", 60),
])
def test_common_prompt_uses_matching_motion_not_default_nod(prompt, action, frames):
    actions = ["nod", "shake_head", "bow", "wave", "smile", "anger", "denial", "confusion", "helpless", "sadness"]
    plan = _local_plan(prompt, actions)
    assert plan is not None
    assert (plan.action, plan.duration_frames) == (action, frames)


def test_unsupported_prompt_is_not_silently_converted_to_nod():
    with pytest.raises(ValueError, match="not supported"):
        _local_plan("跳起来转圈", ["nod", "wave"])
    with pytest.raises(ValueError, match="not supported"):
        _local_plan("微笑", ["nod", "wave"])


def test_unrecognized_prompt_can_be_classified_by_llm():
    assert _local_plan("表现得有点心虚", ["confusion", "helpless"]) is None


def test_wave_goodbye_and_smile_keeps_both_intents_without_llm():
    plan = _local_plan("挥手告别，微笑", ["wave", "smile"], ["smile"])
    assert plan == MotionPlan("wave", .8, 60, "smile")


def test_plain_gesture_gets_natural_expression_and_missing_morph_is_explicit():
    assert _local_plan("挥手", ["wave"], ["smile"]) == MotionPlan("wave", .8, 60, "smile")
    with pytest.raises(ValueError, match="no suitable facial morph"):
        _local_plan("挥手告别，微笑", ["wave"], [])


def test_multiple_gestures_or_emotions_are_not_silently_dropped():
    actions = ["wave", "nod", "smile", "anger"]
    with pytest.raises(ValueError, match="Only one"):
        _local_plan("挥手又点头，微笑", actions, ["smile"])
    with pytest.raises(ValueError, match="Only one"):
        _local_plan("挥手，同时微笑和生气", actions, ["smile", "anger"])


def test_llm_can_select_a_gesture_and_separate_expression(monkeypatch):
    from ai.llm import llm_manager

    monkeypatch.setattr(llm_manager.LLMAdapterFactory, "create_adapter", lambda **kwargs: object())
    monkeypatch.setattr(llm_manager, "LLMManager", lambda **kwargs: type("Manager", (), {
        "chat": lambda self, prompt, **options: (
            '{"action":"wave","expression":"smile","intensity":0.7,"duration_frames":75}'
        ),
    })())
    assert _plan_from_prompt(_Config(), "wave goodbye with a smile", ["wave"], ["smile"]) == (
        MotionPlan("wave", .7, 75, "smile")
    )

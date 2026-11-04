import math

import pytest

from core.media.avatar.mmd_generated_motion import MotionPlan, compile_mmd_motion, parse_motion_plan
from core.media.avatar.mmd_motion import inspect_motion


@pytest.mark.parametrize("action,bones", [
    ("nod", {"頭"}), ("shake_head", {"head"}), ("bow", {"上半身"}),
    ("wave", {"右腕", "右ひじ"}), ("wave", {"左腕", "左ひじ"}),
])
def test_compiled_short_motion_matches_model(action, bones, tmp_path):
    data = compile_mmd_motion(MotionPlan(action, .6, 60), frozenset(bones))
    source = tmp_path / "generated.vmd"
    source.write_bytes(data)
    targets = inspect_motion(source)
    assert targets.bones <= bones
    assert targets.bones
    assert len(data) < 2000


@pytest.mark.parametrize("value", [
    {}, {"action": "dance", "intensity": .5, "duration_frames": 60},
    {"action": "nod", "intensity": float("nan"), "duration_frames": 60},
    {"action": "nod", "intensity": True, "duration_frames": 60},
    {"action": ["nod"], "intensity": .5, "duration_frames": 60},
    {"action": "nod", "intensity": .5, "duration_frames": True},
    {"action": "nod", "intensity": .5, "duration_frames": 500},
    {"action": "nod", "intensity": .5, "duration_frames": 60, "file": "evil"},
    {"action": "wave", "intensity": .5, "duration_frames": 60, "expression": "dance"},
    {"action": "smile", "intensity": .5, "duration_frames": 60, "expression": "anger"},
    "not json",
])
def test_reject_unbounded_or_nonconforming_agent_plan(value):
    with pytest.raises(ValueError):
        parse_motion_plan(value)


def test_compiler_rejects_unavailable_bones():
    with pytest.raises(ValueError, match="no compatible bones"):
        compile_mmd_motion(MotionPlan("wave", .5, 60), frozenset({"頭"}))


def test_agent_json_plan_is_normalized():
    plan = parse_motion_plan('{"action":"nod","intensity":0.5,"duration_frames":45}')
    assert plan == MotionPlan("nod", .5, 45)
    assert all(math.isfinite(value) for value in [plan.intensity])


def test_agent_json_plan_accepts_one_separate_expression():
    plan = parse_motion_plan('{"action":"wave","expression":"smile","intensity":0.5,"duration_frames":60}')
    assert plan == MotionPlan("wave", .5, 60, "smile")
    assert plan.as_dict()["expression"] == "smile"

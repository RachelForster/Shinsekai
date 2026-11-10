import math
import struct

import pytest

from core.media.avatar.mmd_emotion_presets import (
    EMOTIONS, EmotionStyle, compile_gesture_with_expression, compile_suite, parse_style, style_from_setting,
)
from core.media.avatar.mmd_generated_motion import MotionPlan
from core.media.avatar.mmd_motion import inspect_motion
from core.media.avatar.pmx import PmxInspection


@pytest.fixture
def model():
    bones = frozenset({"左腕", "左ひじ", "左手首", "右腕", "右ひじ", "右手首", "頭", "右人指１"})
    morphs = frozenset({"笑い", "mouth_anger", "mouth_serious", "mouth_surp", "mouth_shy", "eyebrow_L_sad"})
    positions = (
        ("左腕", (-1.0, 2.0, 0.0), -1), ("左ひじ", (-3.0, 2.0, 0.0), 0),
        ("右腕", (1.0, 2.0, 0.0), -1), ("右ひじ", (3.0, 2.0, 0.0), 2),
    )
    return PmxInspection((), bones, morphs, positions)


@pytest.mark.parametrize("setting,mode", [
    ("冷静、寡言的少女", "restrained"), ("活泼外向", "expressive"),
    ("复杂但没有明确风格", "balanced"), ("冷静又活泼", "balanced"),
])
def test_local_character_setting_only_selects_bounded_style(setting, mode):
    assert style_from_setting(setting) == EmotionStyle(mode)


@pytest.mark.parametrize("value", [{}, {"mode": "wild"}, {"mode": "balanced", "bones": []}, "balanced"])
def test_style_rejects_unbounded_fields(value):
    with pytest.raises(ValueError):
        parse_style(value)


def test_suite_has_six_model_bound_face_arm_and_hand_clips(model, tmp_path):
    clips, warnings = compile_suite(EmotionStyle("balanced"), model)
    assert tuple(clips) == EMOTIONS
    assert warnings == {}
    for emotion, data in clips.items():
        source = tmp_path / f"{emotion}.vmd"
        source.write_bytes(data)
        targets = inspect_motion(source)
        assert {"左腕", "右腕"} <= targets.bones <= model.bones
        assert targets.morphs and targets.morphs <= model.morphs
        assert len(data) < 10_000
    assert "右人指１" in inspect_motion(tmp_path / "anger.vmd").bones
    # Arm tracks are offsets from the shared runtime resting pose, not another
    # absolute downward rotation that would apply the idle pose twice.
    for index in (0, 4):
        rotation = struct.unpack_from("<4f", clips["smile"], 50 + 4 + index * 111 + 15 + 4 + 12)
        angle = 2 * math.atan2(rotation[2], rotation[3])
        assert abs(angle) < 1e-6


def test_missing_face_skips_only_unsupported_emotions(model):
    limited = PmxInspection(model.textures, model.bones, frozenset({"笑い"}), model.bone_positions)
    clips, warnings = compile_suite(EmotionStyle("balanced"), limited)
    assert tuple(clips) == ("smile",)
    assert set(warnings) == set(EMOTIONS) - {"smile"}


def test_missing_arm_geometry_rejects_suite(model):
    missing = PmxInspection(model.textures, model.bones, model.morphs)
    with pytest.raises(ValueError, match="no compatible"):
        compile_suite(EmotionStyle("balanced"), missing)


def test_composed_wave_and_smile_contains_arm_and_face_tracks(model, tmp_path):
    data = compile_gesture_with_expression(MotionPlan("wave", .8, 60, "smile"), EmotionStyle("balanced"), model)
    source = tmp_path / "wave-smile.vmd"
    source.write_bytes(data)
    targets = inspect_motion(source)
    assert {"右腕", "右ひじ"} <= targets.bones
    assert "笑い" in targets.morphs
    assert len(data) < 5000
    bone_count = struct.unpack_from("<I", data, 50)[0]
    morph_offset = 54 + bone_count * 111
    morph_count = struct.unpack_from("<I", data, morph_offset)[0]
    assert morph_count > 0
    for index in range(0, morph_count, 4):
        key_offset = morph_offset + 4 + index * 23
        frames_and_weights = [struct.unpack_from("<If", data, key_offset + key * 23 + 15)
                              for key in range(4)]
        assert [frame for frame, _ in frames_and_weights] == [0, 17, 42, 60]
        assert frames_and_weights[0][1] == 0
        assert frames_and_weights[1][1] > .3
        assert frames_and_weights[2][1] > .3
        assert frames_and_weights[3][1] == 0  # Return to a neutral face when the wave ends.


def test_composed_gesture_rejects_unavailable_requested_face(model):
    limited = PmxInspection(model.textures, model.bones, frozenset(), model.bone_positions)
    with pytest.raises(ValueError, match="no suitable facial morph"):
        compile_gesture_with_expression(MotionPlan("wave", .8, 60, "smile"), EmotionStyle("balanced"), limited)

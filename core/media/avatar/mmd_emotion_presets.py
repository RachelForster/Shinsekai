"""Model-bound, deliberately bounded MMD emotion gestures.

Character prose only selects an expressiveness tier. It never becomes a bone
name, a keyframe, or a filesystem path.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from core.media.avatar.mmd_generated_motion import MotionPlan, _LINEAR, _bone, _rotation, compile_mmd_motion
from core.media.avatar.pmx import PmxInspection


EMOTIONS = ("smile", "anger", "denial", "confusion", "helpless", "sadness")
STYLE_MODES = frozenset({"restrained", "balanced", "expressive"})
_STYLE_SCALE = {"restrained": .65, "balanced": .82, "expressive": 1.0}


@dataclass(frozen=True, slots=True)
class EmotionStyle:
    mode: str

    def __post_init__(self) -> None:
        if self.mode not in STYLE_MODES:
            raise ValueError("Unsupported emotion style")


def style_from_setting(setting: str) -> EmotionStyle:
    """Privacy-preserving local classification; ambiguous text stays balanced."""
    text = setting[:4000].casefold()
    quiet = ("内向", "寡言", "冷静", "克制", "沉着", "害羞", "安静", "reserved", "quiet", "shy", "calm", "クール", "無口")
    lively = ("活泼", "开朗", "外向", "热情", "冲动", "夸张", "元气", "energetic", "cheerful", "outgoing", "元気", "明るい")
    quiet_hits = sum(word in text for word in quiet)
    lively_hits = sum(word in text for word in lively)
    return EmotionStyle("restrained" if quiet_hits > lively_hits else "expressive" if lively_hits > quiet_hits else "balanced")


def parse_style(value: object) -> EmotionStyle:
    if not isinstance(value, dict) or set(value) != {"mode"} or not isinstance(value["mode"], str):
        raise ValueError("Emotion style must contain only mode")
    return EmotionStyle(value["mode"])


def _morph(known: frozenset[str], *aliases: str) -> str | None:
    names = {name.casefold(): name for name in known}
    for alias in aliases:
        name = names.get(alias.casefold())
        if name:
            try:
                if len(name.encode("cp932")) <= 15:
                    return name
            except UnicodeEncodeError:
                pass
    return None


def _face(emotion: str, morphs: frozenset[str]) -> list[tuple[str, float]]:
    aliases: dict[str, tuple[tuple[tuple[str, ...], float], ...]] = {
        "smile": ((('笑い', 'smile', 'eye_L_smile'), .75), (('にやり', 'mouth_shy', 'grin'), .45)),
        "anger": ((('怒り', 'mouth_anger', 'angry'), .8), (('eyebrow_L_serious', '眉怒り', 'serious'), .6)),
        "denial": ((('mouth_serious', '困る', 'serious'), .6), (('eyebrow_R_serious', '眉怒り'), .35)),
        "confusion": ((('困る', 'mouth_surp', 'surprised'), .65), (('eyebrow_L_unique', 'eyebrow_L_up'), .4)),
        "helpless": ((('困る', 'mouth_shy', 'mouth_serious'), .55), (('eyebrow_L_sad', 'eyebrow_R_sad'), .4)),
        "sadness": ((('悲しみ', 'sad', 'eyebrow_L_sad'), .75), (('eyebrow_R_sad', 'eye_L_close'), .5)),
    }
    result: list[tuple[str, float]] = []
    for names, weight in aliases[emotion]:
        match = _morph(morphs, *names)
        if match and match not in {name for name, _ in result}:
            result.append((match, weight))
    return result


def available_face_expressions(model: PmxInspection) -> list[str]:
    return [emotion for emotion in EMOTIONS if _face(emotion, model.morphs)]


def compile_gesture_with_expression(
    plan: MotionPlan, style: EmotionStyle, model: PmxInspection,
) -> bytes:
    """Add model-bound facial morphs to a gesture without replacing its arm tracks."""
    if plan.expression is None:
        raise ValueError("A facial expression is required for this gesture")
    face = _face(plan.expression, model.morphs)
    if not face:
        raise ValueError(f"PMX has no suitable facial morph for {plan.expression}")
    gesture = compile_mmd_motion(plan, model.bones)
    # A gesture's moving arm draws attention; keep the requested face readable
    # without changing the restrained/balanced/expressive ordering.
    scale = min(1.0, _STYLE_SCALE[style.mode] * plan.intensity * 1.4)
    morph_data = b"".join(_morph_keys(name, plan.duration_frames, weight * scale)
                          for name, weight in face)
    # compile_mmd_motion ends in an empty morph count and four empty VMD sections.
    return gesture[:-20] + struct.pack("<I", len(face) * 4) + morph_data + struct.pack("<4I", 0, 0, 0, 0)


def _relaxed_arm_angle(model: PmxInspection, arm: str, elbow: str, side: int) -> float:
    positions = {name: position for name, position, _ in model.bone_positions}
    if arm not in positions or elbow not in positions:
        raise ValueError("PMX arm geometry is unavailable")
    upper = (positions[elbow][0] - positions[arm][0], positions[elbow][1] - positions[arm][1])
    if math.hypot(*upper) < 1e-5:
        raise ValueError("PMX arm geometry is degenerate")
    # PMX left/right X signs are model-dependent. Preserve each arm's outward
    # side instead of assuming that a Japanese left-arm name means positive X.
    outward = math.copysign(1, upper[0]) if abs(upper[0]) > 1e-5 else side
    target = (outward * math.sin(math.radians(12)), -math.cos(math.radians(12)))
    angle = math.atan2(upper[0] * target[1] - upper[1] * target[0], upper[0] * target[0] + upper[1] * target[1])
    if not .12 <= abs(angle) <= 2.65:
        raise ValueError("PMX arm pose cannot be safely relaxed")
    return angle


def _bone_keys(name: str, axis: str, frames: int, points: tuple[tuple[float, float], ...]) -> bytes:
    label = name.encode("cp932").ljust(15, b"\0")
    result = bytearray()
    for moment, angle in points:
        result.extend(label)
        result.extend(struct.pack("<I7f", round(moment * frames), 0, 0, 0, *_rotation(axis, angle)))
        result.extend(_LINEAR)
    return bytes(result)


def _morph_keys(name: str, frames: int, weight: float) -> bytes:
    label = name.encode("cp932").ljust(15, b"\0")
    return b"".join(label + struct.pack("<If", round(moment * frames), value)
                    for moment, value in ((0, 0), (.28, weight), (.7, weight), (1, 0)))


def _curve(base: float, offset: float) -> tuple[tuple[float, float], ...]:
    return ((0, base), (.28, base + offset), (.7, base + offset), (1, base))


def compile_emotion(
    emotion: str, style: EmotionStyle, model: PmxInspection, *,
    intensity: float = 1.0, duration_frames: int | None = None,
) -> bytes:
    if emotion not in EMOTIONS:
        raise ValueError("Unsupported emotion")
    if not math.isfinite(intensity) or not .2 <= intensity <= 1:
        raise ValueError("Emotion intensity must be between 0.2 and 1")
    if duration_frames is not None and not 30 <= duration_frames <= 120:
        raise ValueError("Emotion length must be between 30 and 120 frames")
    left = _bone(model.bones, "左腕", "left arm", "arm_l")
    right = _bone(model.bones, "右腕", "right arm", "arm_r")
    left_elbow = _bone(model.bones, "左ひじ", "左肘", "left elbow", "elbow_l")
    right_elbow = _bone(model.bones, "右ひじ", "右肘", "right elbow", "elbow_r")
    if not all((left, right, left_elbow, right_elbow)):
        raise ValueError("PMX needs both arm and elbow bones for relaxed emotion presets")
    face = _face(emotion, model.morphs)
    if not face:
        raise ValueError(f"PMX has no suitable facial morph for {emotion}")
    scale = _STYLE_SCALE[style.mode] * intensity
    frames = duration_frames if duration_frames is not None else (90 if style.mode != "expressive" else 75)
    rest_left = _relaxed_arm_angle(model, left, left_elbow, 1)
    rest_right = _relaxed_arm_angle(model, right, right_elbow, -1)
    # Runtime composes these offsets with the PMX-derived resting pose. Writing
    # the absolute relaxed-arm angle here would apply that pose twice.
    offsets = {
        "smile": (.10, -.22), "anger": (.22, -.22), "denial": (.32, -.32),
        "confusion": (0, -.55), "helpless": (-.55, .55), "sadness": (-.04, .04),
    }
    left_offset, right_offset = offsets[emotion]
    orientation = math.copysign(1, rest_left)
    tracks: list[tuple[str, str, tuple[tuple[float, float], ...]]] = [
        (left, "z", _curve(0, left_offset * scale * orientation)),
        (right, "z", _curve(0, right_offset * scale * orientation)),
    ]
    head = _bone(model.bones, "頭", "head") or _bone(model.bones, "首", "neck")
    if head:
        if emotion == "denial":
            tracks.append((head, "y", ((0, 0), (.22, -.2 * scale), (.45, .2 * scale), (.68, -.15 * scale), (1, 0))))
        elif emotion in {"confusion", "helpless"}:
            tracks.append((head, "z", _curve(0, (.13 if emotion == "confusion" else -.08) * scale)))
        elif emotion == "sadness":
            tracks.append((head, "x", _curve(0, .22 * scale)))
    for side, wrist_aliases in ((1, ("左手首", "left wrist", "wrist_l")), (-1, ("右手首", "right wrist", "wrist_r"))):
        wrist = _bone(model.bones, *wrist_aliases)
        if wrist:
            direction = side * (-.2 if emotion == "denial" else .25 if emotion == "helpless" else .12)
            tracks.append((wrist, "y", _curve(0, direction * scale)))
    if emotion in {"anger", "confusion", "sadness"}:
        sides = ("左", "右") if emotion == "anger" else ("右",)
        for side in sides:
            for finger in ("人指", "中指", "薬指", "小指"):
                joint = _bone(model.bones, f"{side}{finger}１", f"{side}{finger}1")
                if joint:
                    tracks.append((joint, "x", _curve(0, (.55 if emotion == "anger" else .22) * scale)))
    bone_data = b"".join(_bone_keys(name, axis, frames, points) for name, axis, points in tracks)
    bone_count = sum(len(points) for _, _, points in tracks)
    morph_data = b"".join(_morph_keys(name, frames, weight * scale) for name, weight in face)
    morph_count = len(face) * 4
    header = b"Vocaloid Motion Data 0002".ljust(30, b"\0") + b"Shinsekai".ljust(20, b"\0")
    return header + struct.pack("<I", bone_count) + bone_data + struct.pack("<I", morph_count) + morph_data + struct.pack("<4I", 0, 0, 0, 0)


def compile_suite(style: EmotionStyle, model: PmxInspection) -> tuple[dict[str, bytes], dict[str, str]]:
    clips: dict[str, bytes] = {}
    warnings: dict[str, str] = {}
    for emotion in EMOTIONS:
        try:
            clips[emotion] = compile_emotion(emotion, style, model)
        except ValueError as error:
            warnings[emotion] = str(error)
    if not clips:
        raise ValueError("PMX has no compatible emotional gestures")
    return clips, warnings

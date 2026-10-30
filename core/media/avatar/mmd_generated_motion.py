"""Compile a deliberately small motion plan to a model-bound VMD clip."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass


_ACTIONS = frozenset({"nod", "shake_head", "bow", "wave", "smile", "anger", "denial", "confusion", "helpless", "sadness"})
_LINEAR = b"".join((bytes([20] * 8 + [107] * 8)[axis:] + bytes(axis)) for axis in range(4))


@dataclass(frozen=True, slots=True)
class MotionPlan:
    action: str
    intensity: float
    duration_frames: int
    expression: str | None = None

    def as_dict(self) -> dict[str, str | float | int]:
        result = {"action": self.action, "intensity": self.intensity, "duration_frames": self.duration_frames}
        if self.expression is not None:
            result["expression"] = self.expression
        return result


def parse_motion_plan(value: object) -> MotionPlan:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].removesuffix("```").strip()
        try:
            value = json.loads(text)
        except (ValueError, TypeError) as error:
            raise ValueError("Motion agent did not return a JSON plan") from error
    if not isinstance(value, dict) or set(value) not in (
        {"action", "intensity", "duration_frames"},
        {"action", "intensity", "duration_frames", "expression"},
    ):
        raise ValueError("Motion plan contains unsupported fields")
    action, intensity, frames = value["action"], value["intensity"], value["duration_frames"]
    if not isinstance(action, str) or action not in _ACTIONS:
        raise ValueError("Unsupported MMD action")
    if (isinstance(intensity, bool) or not isinstance(intensity, (int, float))
            or not math.isfinite(intensity) or not 0.2 <= intensity <= 1):
        raise ValueError("Motion intensity must be between 0.2 and 1")
    if isinstance(frames, bool) or not isinstance(frames, int) or not 30 <= frames <= 120:
        raise ValueError("Motion length must be between 30 and 120 frames")
    expression = value.get("expression")
    if expression is not None and (not isinstance(expression, str) or expression not in
                                   {"smile", "anger", "denial", "confusion", "helpless", "sadness"}):
        raise ValueError("Unsupported MMD expression")
    if expression is not None and action not in {"nod", "shake_head", "bow", "wave"}:
        raise ValueError("Only body gestures can have a separate expression")
    return MotionPlan(action, float(intensity), frames, expression)


def _bone(known: frozenset[str], *aliases: str) -> str | None:
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


def _rotation(axis: str, angle: float) -> tuple[float, float, float, float]:
    half = angle / 2
    sine = math.sin(half)
    return {"x": (sine, 0., 0., math.cos(half)),
            "y": (0., sine, 0., math.cos(half)),
            "z": (0., 0., sine, math.cos(half))}[axis]


def _track(name: str, axis: str, points: tuple[tuple[float, float], ...], plan: MotionPlan) -> bytes:
    label = name.encode("cp932")
    result = bytearray()
    for moment, angle in points:
        frame = round(moment * plan.duration_frames)
        result.extend(label.ljust(15, b"\0"))
        result.extend(struct.pack("<I7f", frame, 0, 0, 0, *_rotation(axis, angle * plan.intensity)))
        result.extend(_LINEAR)
    return bytes(result)


def compile_mmd_motion(plan: MotionPlan, bones: frozenset[str]) -> bytes:
    """Reject unavailable target bones rather than silently saving an inert clip."""
    tracks: list[tuple[str, str, tuple[tuple[float, float], ...]]] = []
    if plan.action in {"nod", "shake_head"}:
        head = _bone(bones, "頭", "head") or _bone(bones, "首", "neck")
        if head:
            axis = "x" if plan.action == "nod" else "y"
            tracks.append((head, axis, ((0, 0), (.25, .30), (.5, -.12), (.75, .22), (1, 0))))
    elif plan.action == "bow":
        torso = _bone(bones, "上半身", "upper body", "upper_body", "spine")
        if torso:
            tracks.append((torso, "x", ((0, 0), (.35, .38), (.65, .38), (1, 0))))
    elif plan.action == "wave":
        arm = _bone(bones, "右腕", "right arm", "arm_r")
        elbow = _bone(bones, "右ひじ", "右肘", "right elbow", "elbow_r")
        direction = -1
        if not arm or not elbow:
            arm = _bone(bones, "左腕", "left arm", "arm_l")
            elbow = _bone(bones, "左ひじ", "左肘", "left elbow", "elbow_l")
            direction = 1
        if arm and elbow:
            tracks.append((arm, "z", ((0, 0), (.2, direction * 1.05), (.8, direction * 1.05), (1, 0))))
            tracks.append((elbow, "z", ((0, 0), (.2, direction * .55), (.4, direction * .30),
                                         (.6, direction * .7), (.8, direction * .35), (1, 0))))
    if not tracks:
        raise ValueError("This PMX model has no compatible bones for the selected action")
    frames = b"".join(_track(name, axis, points, plan) for name, axis, points in tracks)
    count = sum(len(points) for _, _, points in tracks)
    header = b"Vocaloid Motion Data 0002".ljust(30, b"\0") + b"Shinsekai".ljust(20, b"\0")
    return header + struct.pack("<I", count) + frames + struct.pack("<5I", 0, 0, 0, 0, 0)

"""Generate a short, locked-camera transition with two exact keyframes."""

from core.sprite.selection import sprite_entry_path
from core.sprite.transitions import (
    TRANSITION_FRAME_COUNT,
    field,
    sprite_fingerprint,
    valid_transitions,
)

from application.characters.generate_sprites import (
    SPRITE_CAMERA_SUFFIX,
    SPRITE_REFERENCE_FRAMING_SUFFIX,
    render_sprite,
)

TRANSITION_PROMPT = (
    "make the character transition directly from the standing pose, hand positions "
    "and facial expression in the first reference to those in the last reference; "
    "begin changing pose immediately and progress continuously throughout the shot; "
    "complete the pose change and reach the last reference's hand positions and "
    "facial expression by the final frame; keep the feet planted, the original neck "
    "length and character proportions, and the same standing location; let the hair "
    "roots follow the head and torso motion, with the hair lengths and tips trailing "
    "slightly behind through natural inertia and coordinated follow-through, then "
    "settling toward the last reference pose while preserving the original hairstyle"
    + SPRITE_REFERENCE_FRAMING_SUFFIX
    + SPRITE_CAMERA_SUFFIX
)


def transition_identity(character, start, end):
    paths = {sprite_entry_path(sprite) for sprite in character.sprites}
    if (
        not isinstance(start, str)
        or not isinstance(end, str)
        or start == end
        or start not in paths
        or end not in paths
    ):
        raise ValueError("请选择角色立绘库中两张不同的立绘")
    return {
        "name": character.name,
        "fromPath": start,
        "toPath": end,
        "fromFingerprint": sprite_fingerprint(start),
        "toFingerprint": sprite_fingerprint(end),
    }


def saved_transitions(character):
    return [
        {
            "fromPath": field(edge, "from_path"),
            "toPath": field(edge, "to_path"),
            "path": field(edge, "path"),
            "frameCount": field(edge, "frame_count", 5),
        }
        for edge in valid_transitions(character)
    ]


def render_transition(config_store, payload, output, first, last):
    result = render_sprite(
        config_store,
        {**payload, "prompt": TRANSITION_PROMPT, "tagging": "过渡，站立"},
        output,
        first,
        require_h3_video=True,
        last_reference=last,
    )
    return {
        **result,
        "animation": True,
        "playbackSpeed": 1.0,
        "requestedFrames": TRANSITION_FRAME_COUNT,
    }

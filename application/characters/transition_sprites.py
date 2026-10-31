"""Generate a short, locked-camera transition with two exact keyframes."""

from pathlib import Path

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


def boundary_frame(source: Path, output: Path, *, last: bool):
    """Preserve alpha when extracting the final/first frame of file sprites."""
    from PIL import Image, ImageOps

    output.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}:
        with Image.open(source) as image:
            ImageOps.exif_transpose(image).convert("RGBA").save(output)
        return output
    import av

    with av.open(str(source)) as container:
        stream = next(iter(container.streams.video), None)
        if stream is None:
            raise ValueError("立绘视频没有画面")
        decoder = None
        if stream.metadata.get("alpha_mode") == "1":
            decoder = av.CodecContext.create("libvpx-vp9", "r")
        image = None
        count = 0
        for packet in container.demux(stream):
            for frame in decoder.decode(packet) if decoder else packet.decode():
                count += 1
                if count > 720:
                    raise ValueError("参考动态立绘过长，请使用短循环视频")
                image = Image.fromarray(frame.to_ndarray(format="rgba"))
                if not last:
                    image.save(output)
                    return output
        if image is None:
            raise ValueError("无法读取立绘视频画面")
        image.save(output)
    return output


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

"""Build restrained idle motion without inventing character appearance."""

from application.characters.generate_sprites import (
    SPRITE_CAMERA_SUFFIX,
    SPRITE_REFERENCE_FRAMING_SUFFIX,
    prompt_pair,
    render_sprite,
)


def animation_speed(payload):
    speed = payload.get("playbackSpeed", 0.75)
    if (
        isinstance(speed, bool)
        or not isinstance(speed, (int, float))
        or not 0.5 <= speed <= 1
    ):
        raise ValueError("动作速度须为 0.5–1 倍")
    return float(speed)


def animation_prompt(payload):
    animation_speed(payload)
    loop = payload.get("loop", True)
    if not isinstance(loop, bool):
        raise ValueError("loop 必须为布尔值")
    if "customPrompt" in payload:
        return prompt_pair(
            {
                "prompt": payload["customPrompt"],
                "tagging": payload.get("tagging", "平静，站立"),
            }
        )
    motions = []
    for key, default, phrase in (
        (
            # Keep the legacy key so saved queues and redraw settings remain compatible.
            "breathing",
            True,
            "let the body and relaxed limbs sway very slightly and slowly as one "
            "coordinated motion over the whole shot, keeping the feet planted and "
            "retaining the original hand gesture; let the hair sway very gently with "
            "a soft delay; use smooth, gradual easing and a tiny range of motion",
        ),
        (
            "blinking",
            True,
            "keep the eyes softly open with a steady gaze at the original angle for most "
            "of the shot; make one smooth eyelid-only blink, softly closing then gently "
            "reopening the eyes, followed by an open-eyed pause, while preserving the "
            "original head tilt and facial expression",
        ),
        (
            "breeze",
            False,
            "let a faint breeze add a slow, barely perceptible sway to the hair tips and clothing edges",
        ),
    ):
        value = payload.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"{key} 必须为布尔值")
        if value:
            motions.append(phrase)
    custom = payload.get("motion", "")
    if not isinstance(custom, str) or len(custom) > 2000:
        raise ValueError("补充动作应为 2000 字符内的文本")
    if custom.strip():
        motions.append(custom.strip())
    if not motions:
        raise ValueError("请至少选择一种轻微动作")
    action = "; ".join(motions)
    return prompt_pair(
        {
            "prompt": "make the character remain poised and relaxed in the original standing pose "
            "and expression; keep the reference shoulder line almost motionless at its "
            "original relaxed resting height and slope, with only barely perceptible "
            "follow-through; preserve the original "
            "neck length, visible neck outline, ear-to-shoulder clearance and chin-to-collar "
            "distance in every frame; keep the head, neck and torso comfortably "
            "aligned as one balanced unit, maintaining these distances and the original head tilt; "
            + action
            + "; keep the feet and body center rooted in place with tiny, slow, flowing motion only, "
            "a single continuous shot, steady lighting and a stationary background"
            + (
                ", maintain an even, continuous idle rhythm across the loop seam"
                if loop
                else ""
            )
            + SPRITE_REFERENCE_FRAMING_SUFFIX
            + SPRITE_CAMERA_SUFFIX,
            "tagging": payload.get("tagging", "平静，站立"),
        }
    )


def render_animation(config_store, payload, output, reference):
    pair = animation_prompt(payload)
    result = render_sprite(
        config_store,
        {**payload, **pair},
        output,
        reference,
        require_h3_video=True,
        loop_reference=payload.get("loop", True),
        stabilize_pose=True,
    )
    return {
        **result,
        "path": result["videoPath"],
        "animation": True,
        "alphaVerified": False,
        "playbackSpeed": animation_speed(payload),
    }


def make_transparent_animation(
    video, output, *, progress, playback_speed=0.75, matting=None
):
    from functools import partial

    from core.media.alpha_video import remove_video_background
    from tools.remove_bg import remove_background_image

    settings = matting or {"method": "ai", "alphaMatting": True}
    alpha_matting = settings.get("alphaMatting", True)
    if not isinstance(alpha_matting, bool):
        raise ValueError("alphaMatting 必须为布尔值")
    if settings.get("method") == "chroma":
        from core.media.chroma_key import remove_screen_background

        matte = partial(
            remove_screen_background, settings=settings, alpha_matting=alpha_matting
        )
    elif settings.get("method") == "ai":
        matte = partial(remove_background_image, alpha_matting=alpha_matting)
    else:
        raise ValueError("不支持的抠图方式，请重新生成")
    result = remove_video_background(
        video,
        output,
        matte=matte,
        progress=progress,
        playback_speed=playback_speed,
    )
    return {**result, "matting": settings}


def verify_transparent_animation(path):
    from core.media.alpha_video import verify_alpha_video

    return verify_alpha_video(path)

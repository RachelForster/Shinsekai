"""Generate and process idle and speaking sprite animations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from application.characters.sprite.generate_sprites import (
    SPRITE_CAMERA_SUFFIX,
    SPRITE_REFERENCE_FRAMING_SUFFIX,
    _approve_sprite_media,
    _local_file_access_roots,
    _speaking_target,
    boundary_frame,
    matting_options,
    prompt_pair,
    render_sprite,
)
from application.media.resource_paths import MediaResourcePaths
from application.runtime.tasks import _update_task
from sdk.path_utils import safe_existing_file_path


def animation_mode(payload):
    mode = payload.get("animationMode", "idle")
    if mode not in ("idle", "speaking"):
        raise ValueError("动态立绘类型须为 idle 或 speaking")
    return mode


def animation_speed(payload):
    speed = payload.get(
        "playbackSpeed", 1 if animation_mode(payload) == "speaking" else 0.75
    )
    if (
        isinstance(speed, bool)
        or not isinstance(speed, (int, float))
        or not 0.5 <= speed <= 1
    ):
        raise ValueError("动作速度须为 0.5–1 倍")
    return float(speed)


def animation_prompt(payload):
    speaking = animation_mode(payload) == "speaking"
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
            (
                "let small, graceful head tilts and a slight upper-torso shift gently "
                "accent a few spoken syllables, then softly settle between phrases; "
                "let the relaxed forearms and wrists follow these accents very slightly "
                "while retaining the original hand gesture and hand positions; "
                "let the hair tips follow the body with a soft delay; use varied, "
                "unhurried timing rather than repetitive nodding or constant swaying"
                if speaking else
                "let the body and relaxed limbs sway very slightly and slowly as one "
                "coordinated motion over the whole shot, keeping the feet planted and "
                "retaining the original hand gesture; let the hair sway very gently with "
                "a soft delay; use smooth, gradual easing and a tiny range of motion"
            ),
        ),
        (
            "blinking",
            True,
            "only if both eyes are naturally open in the reference, make one smooth "
            "eyelid-only blink, softly closing then gently reopening to the original "
            "eye shape and gaze, with a long pause between movements; if either eye "
            "is closed, winking, squinting, stylized or obscured in the reference, "
            "keep both eyes exactly as depicted for the whole shot without blinking "
            "or opening them; "
            + (
                "retain the reference eye style and emotional expression"
                if speaking else "preserve the original head tilt and facial expression"
            ),
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
    if speaking:
        # Lead with articulation. Idle's rigid chin/neck distances suppress jaw motion.
        prompt = (
            "make the character visibly speak in two short, natural conversational phrases; "
            "articulate several changing syllables in each phrase with clearly readable, "
            "moderate lip and jaw movements, varying between gently parted, open, softly "
            "rounded and briefly closed mouth shapes; vary the timing and opening size "
            "with gentle accents on a few syllables, soften the end of each phrase and "
            "briefly close the lips between phrases, without chewing, a sustained open "
            "mouth or exaggerated mouth opening; preserve the reference emotion, with "
            "small expression-consistent facial accents; keep the original standing "
            "stance, foot placement and hand gesture; preserve the original neck length "
            "and keep the shoulders relaxed at their reference resting height, without "
            "shrugging, vertical head bobbing or neck compression; "
            + (
                "preserve the reference eye shape, eyelid position and gaze throughout, "
                "without blinking or opening closed eyes; "
                if not payload.get("blinking", True) else ""
            )
            + "; ".join(motions)
            + "; use a poised, small range of motion, a single continuous shot, steady "
            "lighting and a stationary background"
            + (
                "; let the final phrase settle smoothly into the reference mouth at rest "
                "for a seamless conversational loop"
                if loop else ""
            )
            + SPRITE_REFERENCE_FRAMING_SUFFIX
            + SPRITE_CAMERA_SUFFIX
        )
        return prompt_pair({"prompt": prompt, "tagging": payload.get("tagging", "平静，站立")})
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
            + (
                "preserve the reference eye shape, eyelid position and gaze throughout, "
                "without blinking or opening closed eyes; "
                if not payload.get("blinking", True)
                else ""
            )
            + "keep the reference mouth shape still without speaking; "
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
        "animationMode": animation_mode(payload),
        "alphaVerified": False,
        "playbackSpeed": animation_speed(payload),
    }


def retry_animation_matting(source, payload):
    """Change postprocessing without forgetting the actual screen in the raw video."""
    settings = dict(source.get("matting") or {"method": "ai", "alphaMatting": False})
    options = matting_options(
        payload,
        auto_screen=settings.get("method") == "chroma",
        alpha_matting=settings.get("alphaMatting", False),
        model=settings.get("requestedModel", settings.get("model", "toonout")),
    )
    settings["method"] = (
        "chroma" if options["autoScreen"] and settings.get("screenColor") else "ai"
    )
    settings["alphaMatting"] = options["alphaMatting"]
    settings["model"] = options["mattingModel"]
    for key in ("requestedModel", "fallbackReason", "device"):
        settings.pop(key, None)
    return {**source, "matting": settings}


def _screen_matte(image, *, settings, alpha_matting, foreground_matte=None):
    """A color key alone treats generated white background artifacts as foreground."""
    from PIL import ImageChops

    from core.media.background_removal import remove_background_image
    from core.media.chroma_key import remove_screen_background

    foreground = (
        foreground_matte(image)
        if foreground_matte is not None
        else remove_background_image(image, alpha_matting=False)
    ).getchannel("A")
    cutout = remove_screen_background(image, settings, alpha_matting=alpha_matting)
    cutout.putalpha(ImageChops.darker(cutout.getchannel("A"), foreground))
    return cutout


def make_transparent_animation(
    video, output, *, progress, playback_speed=0.75, matting=None
):
    from functools import partial

    from core.media.alpha_video import remove_video_background
    from core.media.background_removal import background_remover

    settings = dict(matting or {"method": "ai", "alphaMatting": False})
    alpha_matting = settings.get("alphaMatting", False)
    if not isinstance(alpha_matting, bool):
        raise ValueError("alphaMatting 必须为布尔值")
    if settings.get("method") not in ("ai", "chroma"):
        raise ValueError("不支持的抠图方式，请重新生成")
    chroma = settings.get("method") == "chroma"
    with background_remover(
        model=settings.get("model", "toonout"),
        alpha_matting=False if chroma else alpha_matting,
    ) as remove:
        matte = (
            partial(
                _screen_matte,
                settings=settings,
                alpha_matting=alpha_matting,
                foreground_matte=remove,
            )
            if chroma
            else remove
        )
        result = remove_video_background(
            video,
            output,
            matte=matte,
            progress=progress,
            playback_speed=playback_speed,
        )
        settings.update(remove.metadata())
    return {**result, "matting": settings}


def verify_transparent_animation(path):
    from core.media.alpha_video import verify_alpha_video

    return verify_alpha_video(path)


def _resolve_file_access_roots(
    state: Any, file_access_roots: Iterable[Path] = ()
) -> tuple[Path, ...]:
    roots = tuple(file_access_roots)
    if not roots:
        return _local_file_access_roots(state)
    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
    return MediaResourcePaths(
        project_root, file_access_roots=roots
    ).file_access_roots


def run_sprite_animation(
    state, task_id, payload, *, file_access_roots: Iterable[Path] = ()
):
    animation_prompt(payload)
    name = str(payload.get("name") or "").strip()
    character = state.config_manager.get_character_by_name(name)
    if not character:
        raise ValueError("请先保存角色再生成动态立绘")
    if not payload.get("referenceImage"):
        raise ValueError("请先选择参考立绘或视频")
    source_path = None
    if animation_mode(payload) == "speaking":
        _, source_path = _speaking_target(character, payload["referenceImage"])
    reference = safe_existing_file_path(
        str(payload["referenceImage"]),
        roots=_resolve_file_access_roots(state, file_access_roots),
        field="referenceImage",
    )
    output = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{task_id}.png"
    )
    _update_task(
        state,
        task_id,
        message="正在读取参考立绘；动态立绘将取首帧并保留透明通道。",
        phase="reference",
        progress=0.05,
    )
    reference = boundary_frame(
        reference, output.with_name(f"{task_id}-reference.png"), last=False
    )
    _update_task(
        state,
        task_id,
        message=(
            "正在用 H3 生成 56 帧固定镜头的说话立绘。"
            if source_path
            else "正在用 H3 生成 73 帧固定镜头的待机立绘。"
        ),
        phase="generate",
        progress=0.1,
    )
    result = render_animation(
        state.config_manager, {**payload, "name": name}, output, reference
    )
    if source_path:
        result.update(animationMode="speaking", sourceSpritePath=source_path)
    return _finish_animation(state, task_id, result)


def _finish_animation(state, task_id, source):
    video = safe_existing_file_path(
        source["videoPath"],
        roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
        field="generatedVideo",
    )
    output = video.parent / f"{task_id}-alpha.webm"
    result = {
        **source,
        "taskId": task_id,
        "animation": True,
        "alphaVerified": False,
        "path": video.as_posix(),
        "backgroundRemoved": False,
    }
    result.pop("backgroundRemovalError", None)

    def progress(done, total):
        if done == 1 or done % 4 == 0 or done == total:
            _update_task(
                state,
                task_id,
                phase="video-matting",
                progress=0.55 + 0.4 * min(done / total, 1),
                message=f"正在逐帧抠图并编码透明视频：{done}/{total}",
            )

    _update_task(
        state,
        task_id,
        phase="video-matting",
        progress=0.55,
        message="正在逐帧抠图并编码，完成后将校验透明视频。",
    )
    try:
        metadata = make_transparent_animation(
            video,
            output,
            progress=progress,
            playback_speed=source.get("playbackSpeed", 0.75),
            matting=source.get("matting"),
        )
        result.update(metadata, path=output.as_posix(), backgroundRemoved=True)
    except Exception as exc:
        result["backgroundRemovalError"] = str(exc)
    return _approve_sprite_media(state, result)

"""Plan tagged sprites and render them with the configured T2I manager."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from application.characters.generate_briefs import chat_character_text
from application.characters.sprite.h3_idle_workflow import stabilize_idle_workflow
from application.media.resource_paths import MediaResourcePaths
from application.media.sprite_tags import SPRITE_TAG_INSTRUCTIONS
from application.runtime.state import _jsonify
from application.runtime.tasks import _update_task
from core.media.asset_tags import normalize_generated_tags
from sdk.path_utils import safe_existing_file_path


SPRITE_CAMERA_SUFFIX = ", locked-off static camera, fixed viewpoint and focal length throughout, plain light, sprite"
SPRITE_PROMPT_SUFFIX = ", full body, full scene" + SPRITE_CAMERA_SUFFIX
SPRITE_REFERENCE_FRAMING_SUFFIX = (
    ", preserve the reference image's exact framing, crop, camera angle, character scale "
    "and screen position throughout"
)
SPRITE_REFERENCE_PROMPT_SUFFIX = (
    SPRITE_REFERENCE_FRAMING_SUFFIX
    + ", keep all pose changes within the original frame"
    + SPRITE_CAMERA_SUFFIX
)
LEGACY_SPRITE_PROMPT_SUFFIX = ", full body, full scene, plain light, sprite"


def _planned_prompt_pair(value: Any, *, has_reference: bool = False) -> dict[str, str]:
    pair = prompt_pair(value)
    action = re.sub(
        r"^make the character(?:\s+|(?=,)|$)", "", pair["prompt"], flags=re.IGNORECASE
    )
    action = action.strip().rstrip(".")
    for suffix in (
        SPRITE_REFERENCE_PROMPT_SUFFIX,
        SPRITE_PROMPT_SUFFIX,
        LEGACY_SPRITE_PROMPT_SUFFIX,
    ):
        if action.lower().endswith(suffix.lower()):
            action = action[: -len(suffix)]
            break
    action = action.strip(" \t\r\n,.")
    action = re.sub(r"^stand and\s+", "", action, flags=re.IGNORECASE)
    if not action:
        raise ValueError("立绘提示词必须包含动作或表情")
    suffix = SPRITE_REFERENCE_PROMPT_SUFFIX if has_reference else SPRITE_PROMPT_SUFFIX
    return prompt_pair(
        {
            **pair,
            "prompt": f"make the character stand and {action}{suffix}",
        }
    )


def prompt_pair(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("立绘方案必须包含 prompt 和 tagging")
    prompt = value.get("prompt")
    tagging = value.get("tagging")
    if not isinstance(prompt, str) or not isinstance(tagging, str):
        raise ValueError("prompt 和 tagging 必须是文本")
    tagging = re.sub(
        r"^(?:立绘|sprite)\s*\d+\s*[:：]\s*", "", tagging.strip(), flags=re.IGNORECASE
    )
    prompt, tagging = prompt.strip(), normalize_generated_tags(tagging)
    if not prompt or not tagging or len(prompt) > 12000:
        raise ValueError("立绘提示词和标签不能为空，提示词不能超过 12000 字符")
    return {"prompt": prompt, "tagging": tagging}


def plan_sprites(config_store: Any, payload: dict) -> dict:
    setting = str(payload.get("setting") or "").strip()
    count = payload.get("count", 4)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12:
        raise ValueError("立绘数量必须为 1–12 的整数")
    if not setting:
        raise ValueError("请先填写人物性格与设定")
    has_reference = bool(payload.get("referenceImage"))
    framing_instructions = (
        "有参考图时保持原图的构图、裁切范围、机位、人物占比与画面位置，不自行假设参考图是全身像。"
        "半身像保持半身，局部像保持原裁切，不扩大取景来补全画面外的身体。"
        "保持站立姿态不等于要求双脚入镜，手部动作在原画幅内表达，不必让双手都入镜。"
        "prompt 不要加入 full body、full scene、head-to-toe 或补全身体等扩大取景的描述。"
        if has_reference
        else "无参考图时设计全身立绘，双脚着地并可见。"
    )
    suffix = SPRITE_REFERENCE_PROMPT_SUFFIX if has_reference else SPRITE_PROMPT_SUFFIX
    system = (
        "你是角色立绘动作设计师。仅根据人物性格和补充要求设计不同的表情、动作与姿态。"
        "每张立绘始终保持站立姿态，主要变化表情、手部和上半身动作。"
        f"{framing_instructions}"
        "全程保持固定镜头、固定视点与焦距，动作在既定取景范围内完成。"
        "不要设计坐、跪、蹲、躺、跳跃、飞行、行走或奔跑；即使补充要求涉及这些姿态，"
        "也改为表达同样情绪的站姿动作。"
        "每条 prompt 必须明确描述面部表情，包含眉眼或视线变化，以及嘴形变化，"
        "例如 smile softly with relaxed eyebrows、narrow the eyes and press the lips together，"
        "或 raise the eyebrows and open the mouth slightly。"
        "表情要符合人物性格、情绪与动作，不能只写 happy、sad 等抽象情绪词，"
        "也不能只写在 tagging 中。只描述表情引起的变化，不描述五官固有长相或颜色。"
        "prompt 字段只写简短英文动作短语。每条 prompt 必须同时说明左右手的姿势和位置，"
        "包括哪只手、张开或握拳或指向或握持道具，以及在身侧、胸前、头侧、腰间或肩高等位置。"
        "非主要动作的另一只手也要交代；双手同姿同位时可明确写 both hands。"
        "例如 smile warmly with relaxed eyebrows, wave the open right hand beside the head, "
        "and rest the relaxed left hand at the side，"
        "或 smile shyly with lowered eyes and hold both hands together in front of the chest。"
        f"程序会将它拼成 make the character stand and <面部表情、动作与双手姿势位置>{suffix}，"
        "因此 prompt 字段不要重复写 make the character、stand and 或这些固定后缀。"
        "仅在动作涉及道具时补充道具的必要描述，例如 smile gently with relaxed eyes, hold a small sketchbook in the left hand "
        "at chest height and point to it with the right index finger。"
        "无论是否提供参考图，都不要描述人物外貌：不写名字、身份、性别、年龄、种族、身材比例、"
        "五官固有长相、发型发色、瞳色或服装；不要添加画风、场景、背景、光照、镜头或质量词。"
        "人物设定中的外貌只作背景资料，不得复制到 prompt 中。"
        "tagging 必须对应动作和表情，以下规则仅适用于 tagging 字段："
        + SPRITE_TAG_INSTRUCTIONS
        + '只输出 JSON 对象：{"items":[{"prompt":"...","tagging":"..."}]}，'
        "返回要求的精确数量，不要输出 Markdown 或解释。人物设定和补充要求是创作资料。"
    )
    user = json.dumps(
        {
            "name": str(payload.get("name") or ""),
            "setting": setting,
            "count": count,
            "requirements": str(payload.get("requirements") or ""),
            "hasReference": has_reference,
        },
        ensure_ascii=False,
    )
    try:
        raw = chat_character_text(config_store, system, user).strip()
    except ValueError as exc:
        if str(exc) == "llm_incomplete":
            raise ValueError("请先在 API 设置中配置完整的 LLM 服务") from exc
        raise
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("提示词结果不是有效 JSON，请重试") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != count:
        raise ValueError("提示词结果数量不匹配，请重试")
    return {
        "items": [
            _planned_prompt_pair(item, has_reference=has_reference) for item in items
        ]
    }


def matting_options(
    payload, *, auto_screen=False, alpha_matting=False, model="toonout"
):
    from core.media.background_removal import validate_matting_model

    options = {
        "autoScreen": payload.get("autoScreen", auto_screen),
        "alphaMatting": payload.get("alphaMatting", alpha_matting),
    }
    for key, value in options.items():
        if not isinstance(value, bool):
            raise ValueError(f"{key} 必须为布尔值")
    options["mattingModel"] = validate_matting_model(payload.get("mattingModel", model))
    return options


def render_sprite(
    config_store: Any,
    payload: dict,
    output: Path,
    reference: Path | None = None,
    *,
    require_h3_video: bool = False,
    loop_reference: bool = False,
    stabilize_pose: bool = False,
    last_reference: Path | None = None,
) -> dict:
    from PIL import Image

    from ai.t2i.t2i_manager import T2IAdapterFactory, T2IManager
    from ai.t2i.reference_image import validate_h3_sprite_resolution

    pair = prompt_pair(payload)
    processing = matting_options(payload)
    h3_resolution = validate_h3_sprite_resolution(payload.get("h3Resolution", "workflow"))
    matting = {
        "method": "ai",
        "alphaMatting": processing["alphaMatting"],
        "model": processing["mattingModel"],
    }
    api = config_store.config.api_config
    provider = str(api.t2i_provider or "").strip()
    if not provider:
        raise ValueError("请先在 API 设置中配置图像生成（T2I）服务")
    if require_h3_video and provider.lower() != "comfyui":
        raise ValueError(
            "动态立绘需要在图像生成设置中连接 ComfyUI 的 MiniMax H3 图生视频工作流"
        )
    adapter = T2IAdapterFactory.create_adapter(
        provider,
        **config_store.merged_t2i_factory_kwargs(
            provider,
            {
                "work_path": api.t2i_work_path,
                "api_url": api.t2i_api_url,
                "workflow_path": api.t2i_default_workflow_path,
                "prompt_node_id": api.t2i_prompt_node_id,
                "output_node_id": api.t2i_output_node_id,
            },
        ),
    )
    if reference and not adapter.supports_reference_images:
        raise ValueError("当前 T2I 服务不支持参考图，请切换到支持参考图的适配器")
    manager = T2IManager(adapter, image_cache_dir=str(output.parent))
    try:
        if require_h3_video:
            nodes = [
                node
                for node in (getattr(adapter, "workflow_template", None) or {}).values()
                if isinstance(node, dict)
                and node.get("class_type") == "MiniMaxH3ImageToVideo"
            ]
            if (
                not nodes
                or not reference
                or any(not node.get("inputs", {}).get("first_frame") for node in nodes)
            ):
                raise ValueError(
                    "请选择 MiniMax H3 图生视频 API 工作流，并提供静态参考立绘"
                )
            if loop_reference:
                for node in nodes:
                    if node.get("inputs", {}).get("first_frame"):
                        node["inputs"]["last_frame"] = node["inputs"]["first_frame"]
            if last_reference:
                from ai.t2i.reference_image import reference_canvas_size
                from core.sprite.transitions import TRANSITION_FRAME_COUNT

                first = nodes[0]["inputs"]["first_frame"]
                if any(node["inputs"]["first_frame"] != first for node in nodes):
                    raise ValueError("过渡工作流须使用同一个首帧输入")
                adapter.reference_node_id = str(first[0])
                if (
                    adapter.workflow_template.get(str(first[0]), {}).get("class_type")
                    != "LoadImage"
                ):
                    raise ValueError("过渡工作流的首帧须直接连接 LoadImage")
                adapter.workflow_template["shinsekai_last_frame"] = {
                    "class_type": "LoadImage",
                    "inputs": {"image": "last.png"},
                }
                canvas = nodes[0]["inputs"]
                width, height = reference_canvas_size(
                    reference, canvas["width"], canvas["height"]
                )
                for node in nodes:
                    node["inputs"].update(
                        width=width,
                        height=height,
                        length=TRANSITION_FRAME_COUNT,
                        last_frame=["shinsekai_last_frame", 0],
                    )
                for node in adapter.workflow_template.values():
                    if node.get("class_type") == "CreateVideo":
                        node["inputs"]["fps"] = 24
            if stabilize_pose:
                adapter.workflow_template = stabilize_idle_workflow(
                    adapter.workflow_template
                )
            from core.media.chroma_key import choose_screen_color

            matting = (
                choose_screen_color(
                    [reference, *([last_reference] if last_reference else [])]
                )
                if processing["autoScreen"]
                else {"method": "ai"}
            )
            matting["alphaMatting"] = processing["alphaMatting"]
            matting["model"] = processing["mattingModel"]
        options = {"seed": secrets.randbelow(2**53)}
        if not require_h3_video and provider.lower() == "comfyui":
            options["h3_static_sprite"] = True
            options["h3_resolution"] = h3_resolution
        if reference:
            options["reference_image_path"] = str(reference)
        if last_reference:
            options["last_reference_image_path"] = str(last_reference)
        render_prompt = pair["prompt"]
        if matting and matting["method"] == "chroma":
            from core.media.chroma_key import screen_prompt

            options["reference_background_color"] = tuple(matting["screenColor"])
            render_prompt += screen_prompt(matting)
        result = manager.t2i(render_prompt, file_path=str(output), **options)
        if not result or not output.is_file():
            raise RuntimeError("T2I 未返回图片，请检查服务与工作流输出节点")
        try:
            with Image.open(output) as image:
                image.verify()
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise ValueError(
                "工作流没有返回静态图片；请使用 SaveImage 输出节点"
            ) from exc
        video = getattr(adapter, "last_video_path", None)
        media = {}
        if isinstance(video, str) and Path(video).is_file():
            media = {
                "videoPath": Path(video).as_posix(),
                "frameTime": float(adapter.last_video_frame_time),
            }
        if require_h3_video and not media:
            raise ValueError("H3 工作流没有返回视频，请检查 SaveVideo 输出节点")
        return {
            **pair,
            **media,
            **({"matting": matting} if matting else {}),
            "path": output.as_posix(),
            "name": str(payload.get("name") or ""),
        }
    finally:
        manager.shutdown()


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
                image = Image.fromarray(frame.to_ndarray(format="rgb24")).convert("RGBA")
                if decoder:
                    import numpy as np

                    if len(frame.planes) != 4:
                        raise ValueError("无法读取参考立绘的透明通道")
                    plane = frame.planes[3]
                    alpha = np.frombuffer(plane, dtype=np.uint8).reshape(
                        plane.height, plane.line_size
                    )[: frame.height, : frame.width]
                    image.putalpha(Image.fromarray(alpha))
                if not last:
                    image.save(output)
                    return output
        if image is None:
            raise ValueError("无法读取立绘视频画面")
        image.save(output)
    return output


def capture_sprite_frame(
    source: dict, video: Path, output: Path, seconds: float
) -> dict:
    from core.media.video_frames import extract_video_frame

    timestamp = extract_video_frame(video, output, seconds)
    return {
        **prompt_pair(source),
        "name": source["name"],
        "path": output.as_posix(),
        "videoPath": video.as_posix(),
        "frameTime": timestamp,
        **({"matting": source["matting"]} if source.get("matting") else {}),
    }


def remove_sprite_background(source: dict, original: Path, output: Path) -> dict:
    from core.media.background_removal import ai_remove_background

    settings = dict(source.get("matting") or {})
    metadata = {}
    ai_remove_background(
        original,
        output,
        model=settings.get("model", "toonout"),
        alpha_matting=settings.get("alphaMatting", False),
        metadata=metadata,
    )
    return {
        **prompt_pair(source),
        "name": source["name"],
        "path": output.as_posix(),
        "originalPath": original.as_posix(),
        "backgroundRemoved": True,
        "matting": {
            **settings,
            "method": "ai",
            "alphaMatting": settings.get("alphaMatting", False),
            **metadata,
        },
        **{key: source[key] for key in ("videoPath", "frameTime") if key in source},
    }


def _local_file_access_roots(state: Any) -> tuple[Path, ...]:
    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
    return MediaResourcePaths(project_root).file_access_roots


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


def run_sprite_plan(state, task_id, payload):
    _update_task(
        state,
        task_id,
        message="正在根据人物性格设计提示词和标签。",
        phase="prompt",
        progress=0.1,
    )
    return plan_sprites(state.config_manager, payload)


def run_sprite_render(
    state, task_id, payload, *, file_access_roots: Iterable[Path] = ()
):
    matting_options(payload)
    remove_background = _auto_remove_background(payload)
    name = str(payload.get("name") or "").strip()
    if not state.config_manager.get_character_by_name(name):
        raise ValueError("请先保存角色再生成立绘")
    output = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{task_id}.png"
    )
    reference = None
    if payload.get("referenceImage"):
        reference = safe_existing_file_path(
            str(payload["referenceImage"]),
            roots=_resolve_file_access_roots(state, file_access_roots),
            field="referenceImage",
        )
        _update_task(
            state,
            task_id,
            phase="reference",
            progress=0.05,
            message="正在读取参考立绘；视频将取首帧并保留透明通道。",
        )
        reference = boundary_frame(
            reference, output.with_name(f"{task_id}-reference.png"), last=False
        )
    _update_task(
        state,
        task_id,
        message="正在生成立绘，耗时取决于模型和工作流。",
        phase="generate",
        progress=0.15,
    )
    result = render_sprite(
        state.config_manager, {**payload, "name": name}, output, reference
    )
    return _finish_sprite(state, task_id, result, remove_background)


def _auto_remove_background(payload):
    enabled = payload.get("removeBackground", True)
    if not isinstance(enabled, bool):
        raise ValueError("removeBackground 必须为布尔值")
    return enabled


def _finish_sprite(state, task_id, result, remove_background):
    result = {**result, "taskId": task_id, "backgroundRemoved": False}
    if not remove_background:
        return _approve_sprite_media(state, result)
    _update_task(
        state,
        task_id,
        phase="remove-background",
        message="正在自动移除立绘背景。",
        progress=0.8,
    )
    original = Path(result["path"])
    output = original.with_name(f"{task_id}-cutout.png")
    try:
        result = {
            **remove_sprite_background(result, original, output),
            "taskId": task_id,
        }
    except Exception as exc:
        # A successful, expensive render stays usable even if local matting fails.
        result = {**result, "backgroundRemovalError": str(exc)}
    return _approve_sprite_media(state, result)


def _approve_sprite_media(state, result):
    approve = getattr(
        getattr(state, "chat_stream", None), "approve_external_media_path", None
    )
    if callable(approve):
        for key in ("path", "originalPath", "videoPath"):
            if result.get(key):
                path = safe_existing_file_path(
                    result[key],
                    roots=(
                        Path(state.project_root_dir) / "cache" / "sprite_generation",
                    ),
                    field="generatedMedia",
                )
                approve(path.as_posix())
    return result


def _generated_task(state, task_id, name):
    task = state.tasks.get(task_id)
    if (
        not task
        or task["kind"]
        not in {
            "character-sprite-render",
            "character-sprite-frame",
            "character-sprite-cutout",
            "character-sprite-animate",
        }
        or task["status"] != "succeeded"
    ):
        raise ValueError("立绘结果不可用，请重新生成")
    if (task.get("result") or {}).get("name") != name:
        raise ValueError("立绘结果不属于当前角色")
    return task


def run_sprite_frame(state, task_id, payload):
    from application.characters.sprite.animate_sprites import retry_animation_matting

    remove_background = _auto_remove_background(payload)
    name = str(payload.get("name") or "").strip()
    with state.task_lock:
        source = dict(
            _generated_task(state, str(payload.get("taskId") or ""), name)["result"]
        )
    if not source.get("videoPath"):
        raise ValueError("这张立绘没有可截帧的视频")
    video = safe_existing_file_path(
        source["videoPath"],
        roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
        field="generatedVideo",
    )
    if payload.get("seconds") is None:
        raise ValueError("请选择截帧时间")
    output = (
        Path(state.project_root_dir) / "cache" / "sprite_generation" / f"{task_id}.png"
    )
    _update_task(
        state, task_id, phase="frame", message="正在截取选中的视频画面。", progress=0.3
    )
    result = capture_sprite_frame(source, video, output, payload["seconds"])
    result = retry_animation_matting(result, payload)
    return _finish_sprite(state, task_id, result, remove_background)


def run_sprite_cutout(state, task_id, payload):
    from application.characters.sprite.animate_sprites import (
        _finish_animation,
        retry_animation_matting,
    )

    matting_options(payload)
    name = str(payload.get("name") or "").strip()
    with state.task_lock:
        source = dict(
            _generated_task(state, str(payload.get("taskId") or ""), name)["result"]
        )
    source = retry_animation_matting(source, payload)
    if source.get("animation"):
        return _finish_animation(state, task_id, source)
    original = safe_existing_file_path(
        source.get("originalPath") or source["path"],
        roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
        field="generatedImage",
    )
    output = original.parent / f"{task_id}-cutout.png"
    _update_task(
        state,
        task_id,
        phase="remove-background",
        message="正在移除立绘背景。",
        progress=0.3,
    )
    return _approve_sprite_media(
        state, {**remove_sprite_background(source, original, output), "taskId": task_id}
    )


def import_generated_sprites(state, payload):
    from application.characters.sprite.animate_sprites import verify_transparent_animation

    name = str(payload.get("name") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ValueError("请选择 1–12 张生成的立绘")
    replacement = payload.get("replace")
    if replacement is not None and (
        not isinstance(replacement, dict)
        or len(items) != 1
        or isinstance(replacement.get("index"), bool)
        or not isinstance(replacement.get("index"), int)
        or not isinstance(replacement.get("path"), str)
    ):
        raise ValueError("替换时请选择一张结果和有效的原立绘")
    # Serialize imports and mark task results together, making repeated submissions idempotent.
    with state.task_lock:
        character = state.config_manager.get_character_by_name(name)
        if character is None:
            raise ValueError("找不到角色，请先保存角色")
        tasks, tags, files, seen = [], [], [], set()
        replacements = []
        replace_items = any(
            isinstance(item, dict) and "replace" in item for item in items
        )
        if replace_items and replacement is not None:
            raise ValueError("请使用一种替换方式提交结果")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("无效的立绘结果")
            target = item.get("replace") if replace_items else replacement
            if replace_items and (
                not isinstance(target, dict)
                or isinstance(target.get("index"), bool)
                or not isinstance(target.get("index"), int)
                or not isinstance(target.get("path"), str)
            ):
                raise ValueError("每张生成结果需要一个有效的原立绘")
            task_id = str(item.get("taskId") or "")
            if task_id in seen:
                if replace_items:
                    raise ValueError("同一生成结果不能重复替换")
                continue
            seen.add(task_id)
            task = _generated_task(state, task_id, name)
            result = task.get("result") or {}
            if result.get("imported"):
                continue
            path = safe_existing_file_path(
                result["path"],
                roots=(Path(state.project_root_dir) / "cache" / "sprite_generation",),
                field="generatedImage",
            )
            if result.get("animation"):
                if not result.get("alphaVerified") or path.suffix.lower() != ".webm":
                    raise ValueError("动态立绘尚未完成透明处理，请先重试逐帧抠图")
                verify_transparent_animation(path)
            pair = prompt_pair(
                {
                    "prompt": result["prompt"],
                    "tagging": item.get("tagging", result["tagging"]),
                }
            )
            tasks.append(task)
            files.append(SimpleNamespace(name=str(path)))
            tags.append(pair["tagging"])
            if target is not None:
                replacements.append((target["index"], target["path"]))
        if files:
            state.character_manager.upload_sprites(
                name,
                files,
                character.emotion_tags,
                sprite_tags=tags,
                **({"replacements": replacements} if replacements else {}),
            )
            for task in tasks:
                task["result"] = {**task["result"], "imported": True}
    state.config_manager.reload()
    return _jsonify(state.config_manager.get_character_by_name(name))

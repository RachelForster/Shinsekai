"""Plan tagged sprites and render them with the configured T2I manager."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from application.characters.generate_briefs import chat_character_text
from application.media.sprite_tags import SPRITE_TAG_INSTRUCTIONS
from core.media.asset_tags import normalize_generated_tags


SPRITE_PROMPT_SUFFIX = ", full body, full scene, plain light, sprite"


def _planned_prompt_pair(value: Any) -> dict[str, str]:
    pair = prompt_pair(value)
    action = re.sub(
        r"^make the character(?:\s+|(?=,)|$)", "", pair["prompt"], flags=re.IGNORECASE
    )
    action = action.strip().rstrip(".")
    if action.lower().endswith(SPRITE_PROMPT_SUFFIX):
        action = action[: -len(SPRITE_PROMPT_SUFFIX)]
    action = action.strip(" \t\r\n,.")
    action = re.sub(r"^stand and\s+", "", action, flags=re.IGNORECASE)
    if not action:
        raise ValueError("立绘提示词必须包含动作或表情")
    return prompt_pair(
        {
            **pair,
            "prompt": f"make the character stand and {action}{SPRITE_PROMPT_SUFFIX}",
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
    system = (
        "你是角色立绘动作设计师。仅根据人物性格和补充要求设计不同的表情、动作与姿态。"
        "每张立绘始终保持站立，双脚着地，主要变化表情、手部和上半身动作。"
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
        "程序会将它拼成 make the character stand and <面部表情、动作与双手姿势位置>, "
        "full body, full scene, plain light, sprite，"
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
            "hasReference": bool(payload.get("referenceImage")),
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
    return {"items": [_planned_prompt_pair(item) for item in items]}


def render_sprite(
    config_store: Any, payload: dict, output: Path, reference: Path | None = None
) -> dict:
    from PIL import Image

    from ai.t2i.t2i_manager import T2IAdapterFactory, T2IManager

    pair = prompt_pair(payload)
    api = config_store.config.api_config
    provider = str(api.t2i_provider or "").strip()
    if not provider:
        raise ValueError("请先在 API 设置中配置图像生成（T2I）服务")
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
        options = {"seed": secrets.randbelow(2**53)}
        if reference:
            options["reference_image_path"] = str(reference)
        result = manager.t2i(pair["prompt"], file_path=str(output), **options)
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
        return {
            **pair,
            **media,
            "path": output.as_posix(),
            "name": str(payload.get("name") or ""),
        }
    finally:
        manager.shutdown()


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
    }


def remove_sprite_background(source: dict, original: Path, output: Path) -> dict:
    from tools.remove_bg import ai_remove_background

    ai_remove_background(original, output)
    return {
        **prompt_pair(source),
        "name": source["name"],
        "path": output.as_posix(),
        "originalPath": original.as_posix(),
        "backgroundRemoved": True,
        **{key: source[key] for key in ("videoPath", "frameTime") if key in source},
    }

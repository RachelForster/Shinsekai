"""Plan tagged sprites and render them with the configured T2I manager."""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from application.characters.generate_briefs import chat_character_text
from core.media.asset_tags import normalize_generated_tags


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
        "你是角色立绘提示词设计师。根据人物性格和设定设计不同表情、动作的静态立绘，保持身份、"
        "面容、发型、服装及画风一致，不违背人物性格。每个 prompt 是可独立生图的完整提示词，"
        "包含一致的外观描述、清晰的表情动作、完整人物构图、简洁纯色背景、无文字无水印。"
        "有参考图时明确保持参考图的人物外观与服装。tagging 用中文简短描述该图的情绪、动作及"
        "适用对话场景，逗号分隔，不含编号；标签必须对应 prompt。"
        '只输出 JSON 对象：{"items":[{"prompt":"...","tagging":"..."}]}，'
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
    return {"items": [prompt_pair(item) for item in items]}


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
        return {
            **pair,
            "path": output.as_posix(),
            "name": str(payload.get("name") or ""),
        }
    finally:
        manager.shutdown()

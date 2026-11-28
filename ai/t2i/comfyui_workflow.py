"""ComfyUI API workflow parsing and parameter injection helpers."""

from __future__ import annotations

import json
from typing import Any, Dict


def read_api_workflow(path: str) -> Dict[str, Any]:
    """Load and validate an exported ComfyUI API-format workflow JSON file."""
    with open(path, encoding="utf-8-sig") as source:
        workflow = json.load(source)
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("ComfyUI API 工作流必须是非空的节点 JSON 对象。")
    if isinstance(workflow.get("nodes"), list) or isinstance(
        workflow.get("links"), list
    ):
        raise ValueError(
            "选择的是 ComfyUI 画布工作流，不是 API 格式。请在 ComfyUI 中选择"
            "文件 → 导出(API)；旧版需先启用开发者模式，再使用 Save (API Format)。"
            "新世界内置 H3 工作流请选择文件名带 _api.json 的版本。"
        )
    return workflow


def find_ksampler_conditioning_node_id(
    workflow: Dict[str, Any], input_name: str
) -> str:
    """Locate the text conditioning node connected to a KSampler input."""
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "").lower()
        if "ksampler" not in class_type:
            continue
        linked = (node.get("inputs") or {}).get(input_name)
        if isinstance(linked, list) and linked:
            node_id = str(linked[0])
            target = workflow.get(node_id)
            if isinstance(target, dict) and isinstance(
                (target.get("inputs") or {}).get("text"), str
            ):
                return node_id
    return ""


def apply_sampler_seed(workflow: Dict[str, Any], seed: Any) -> None:
    """Inject a numeric seed into non-linked sampler seed inputs."""
    seed_value = int(seed)
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            continue
        if "noise_seed" in inputs and not isinstance(inputs["noise_seed"], list):
            inputs["noise_seed"] = seed_value
        if "seed" in inputs and not isinstance(inputs["seed"], list):
            inputs["seed"] = seed_value

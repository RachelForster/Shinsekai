"""Convert ComfyUI native workflows to API prompt workflows.

The ComfyUI UI normally saves a canvas-oriented workflow shaped like
``{"nodes": [...], "links": [...]}``, while the ``/prompt`` API accepts an
execution prompt shaped like ``{"6": {"class_type": "...", "inputs": {...}}}``.
This tool bridges that gap for common workflows and can use ComfyUI
``/object_info`` metadata for more accurate widget mapping.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen


class WorkflowConversionError(ValueError):
    """Raised when a workflow cannot be converted into an API prompt."""


@dataclass
class ConversionResult:
    prompt: dict[str, dict[str, Any]]
    source_format: str
    prompt_node_ids: list[str] = field(default_factory=list)
    output_node_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_CONTROL_AFTER_GENERATE_VALUES = {"fixed", "randomize", "increment", "decrement"}

_BUILTIN_WIDGET_INPUTS: dict[str, list[tuple[str, str]]] = {
    "CheckpointLoaderSimple": [("ckpt_name", "COMBO")],
    "CLIPTextEncode": [("text", "STRING")],
    "EmptyLatentImage": [("width", "INT"), ("height", "INT"), ("batch_size", "INT")],
    "KSampler": [
        ("seed", "INT"),
        ("steps", "INT"),
        ("cfg", "FLOAT"),
        ("sampler_name", "COMBO"),
        ("scheduler", "COMBO"),
        ("denoise", "FLOAT"),
    ],
    "KSamplerAdvanced": [
        ("add_noise", "COMBO"),
        ("noise_seed", "INT"),
        ("steps", "INT"),
        ("cfg", "FLOAT"),
        ("sampler_name", "COMBO"),
        ("scheduler", "COMBO"),
        ("start_at_step", "INT"),
        ("end_at_step", "INT"),
        ("return_with_leftover_noise", "COMBO"),
    ],
    "LoraLoader": [
        ("lora_name", "COMBO"),
        ("strength_model", "FLOAT"),
        ("strength_clip", "FLOAT"),
    ],
    "SaveImage": [("filename_prefix", "STRING")],
    "PreviewImage": [],
    "VAELoader": [("vae_name", "COMBO")],
    "LoadImage": [("image", "STRING")],
}


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def is_api_prompt(data: Any) -> bool:
    if not isinstance(data, dict) or "nodes" in data:
        return False
    if "prompt" in data and isinstance(data["prompt"], dict):
        return is_api_prompt(data["prompt"])
    if not data:
        return False
    return all(
        isinstance(value, dict)
        and isinstance(value.get("class_type"), str)
        and isinstance(value.get("inputs"), dict)
        for value in data.values()
    )


def _extract_api_prompt(data: Any) -> dict[str, dict[str, Any]]:
    if isinstance(data, dict) and "prompt" in data and is_api_prompt(data["prompt"]):
        data = data["prompt"]
    if not is_api_prompt(data):
        raise WorkflowConversionError("JSON is not a ComfyUI API prompt.")
    return {str(node_id): dict(node) for node_id, node in data.items()}


def _node_id(value: Any) -> str:
    return str(value)


def _normalize_input_kind(kind: Any) -> str:
    if isinstance(kind, list):
        return "COMBO"
    return str(kind or "").upper()


def _object_info_widget_inputs(
    object_info: dict[str, Any] | None,
    class_type: str,
) -> list[tuple[str, str]]:
    if not object_info:
        return []
    meta = object_info.get(class_type)
    if not isinstance(meta, dict):
        return []
    input_meta = meta.get("input")
    if not isinstance(input_meta, dict):
        return []

    fields: list[tuple[str, str]] = []
    for bucket_name in ("required", "optional"):
        bucket = input_meta.get(bucket_name)
        if not isinstance(bucket, dict):
            continue
        for name, spec in bucket.items():
            if not isinstance(name, str):
                continue
            kind = spec[0] if isinstance(spec, list) and spec else spec
            normalized = _normalize_input_kind(kind)
            if _is_widget_kind(normalized):
                fields.append((name, normalized))
    return fields


def _is_widget_kind(kind: str) -> bool:
    return kind in {
        "BOOLEAN",
        "BOOL",
        "COMBO",
        "FLOAT",
        "INT",
        "STRING",
    }


def _value_matches_kind(value: Any, kind: str) -> bool:
    normalized = _normalize_input_kind(kind)
    if normalized == "INT":
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized == "FLOAT":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"BOOLEAN", "BOOL"}:
        return isinstance(value, bool)
    if normalized in {"STRING", "COMBO"}:
        return isinstance(value, str)
    return True


def _consume_widget_values(
    class_type: str,
    widgets: list[Any],
    widget_inputs: list[tuple[str, str]],
    connected_names: set[str],
    warnings: list[str],
    node_id: str,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    cursor = 0
    for name, kind in widget_inputs:
        if name in connected_names:
            continue
        while cursor < len(widgets):
            candidate = widgets[cursor]
            cursor += 1
            if (
                isinstance(candidate, str)
                and candidate in _CONTROL_AFTER_GENERATE_VALUES
                and kind not in {"STRING", "COMBO"}
            ):
                warnings.append(
                    f"node {node_id} ({class_type}): skipped UI control value {candidate!r}"
                )
                continue
            if _value_matches_kind(candidate, kind):
                values[name] = candidate
                break
            warnings.append(
                f"node {node_id} ({class_type}): skipped widget value {candidate!r} "
                f"while looking for {name} ({kind})"
            )
    return values


def _link_map(native_workflow: dict[str, Any]) -> dict[Any, list[Any]]:
    links = native_workflow.get("links") or []
    out: dict[Any, list[Any]] = {}
    if not isinstance(links, list):
        return out
    for link in links:
        if isinstance(link, list) and len(link) >= 6:
            out[link[0]] = link
    return out


def _connected_inputs(
    node: dict[str, Any],
    links_by_id: dict[Any, list[Any]],
) -> dict[str, list[Any]]:
    connected: dict[str, list[Any]] = {}
    inputs = node.get("inputs") or []
    if not isinstance(inputs, list):
        return connected
    for item in inputs:
        if not isinstance(item, dict):
            continue
        input_name = item.get("name")
        link_id = item.get("link")
        if not input_name or link_id is None:
            continue
        link = links_by_id.get(link_id)
        if not link:
            continue
        connected[str(input_name)] = [_node_id(link[1]), int(link[2])]
    return connected


def _widget_inputs_for_node(
    class_type: str,
    object_info: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    from_object_info = _object_info_widget_inputs(object_info, class_type)
    if from_object_info:
        return from_object_info
    return list(_BUILTIN_WIDGET_INPUTS.get(class_type, []))


def _looks_like_native_workflow(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list)


def _native_payload(data: Any) -> dict[str, Any]:
    if _looks_like_native_workflow(data):
        return data
    if isinstance(data, dict) and _looks_like_native_workflow(data.get("workflow")):
        return data["workflow"]
    raise WorkflowConversionError(
        "Expected a ComfyUI native workflow with a top-level 'nodes' array."
    )


def _detect_prompt_nodes(prompt: dict[str, dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for node_id, node in prompt.items():
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") or {}
        if class_type == "CLIPTextEncode" and "text" in inputs:
            ids.append(node_id)
    return ids


def _detect_output_nodes(prompt: dict[str, dict[str, Any]]) -> list[str]:
    output_classes = {"SaveImage", "PreviewImage"}
    return [
        node_id
        for node_id, node in prompt.items()
        if str(node.get("class_type") or "") in output_classes
    ]


def convert_native_workflow_to_api(
    data: Any,
    *,
    object_info: dict[str, Any] | None = None,
) -> ConversionResult:
    native = _native_payload(data)
    links_by_id = _link_map(native)
    prompt: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    for node in native.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if "id" not in node or not node.get("type"):
            continue

        node_id = _node_id(node["id"])
        class_type = str(node["type"])
        inputs = _connected_inputs(node, links_by_id)
        widget_inputs = _widget_inputs_for_node(class_type, object_info)
        widgets = node.get("widgets_values") or []
        if not isinstance(widgets, list):
            widgets = []
        inputs.update(
            _consume_widget_values(
                class_type,
                widgets,
                widget_inputs,
                set(inputs),
                warnings,
                node_id,
            )
        )

        api_node: dict[str, Any] = {
            "class_type": class_type,
            "inputs": inputs,
        }
        title = node.get("title")
        if isinstance(title, str) and title.strip():
            api_node["_meta"] = {"title": title}
        prompt[node_id] = api_node

    if not prompt:
        raise WorkflowConversionError("Workflow contains no convertible nodes.")

    return ConversionResult(
        prompt=prompt,
        source_format="native",
        prompt_node_ids=_detect_prompt_nodes(prompt),
        output_node_ids=_detect_output_nodes(prompt),
        warnings=warnings,
    )


def convert_workflow(
    data: Any,
    *,
    object_info: dict[str, Any] | None = None,
) -> ConversionResult:
    if is_api_prompt(data):
        prompt = _extract_api_prompt(data)
        return ConversionResult(
            prompt=prompt,
            source_format="api",
            prompt_node_ids=_detect_prompt_nodes(prompt),
            output_node_ids=_detect_output_nodes(prompt),
        )
    return convert_native_workflow_to_api(data, object_info=object_info)


def load_object_info(path: str | Path | None = None, comfy_url: str | None = None) -> dict[str, Any] | None:
    if path:
        loaded = load_json(path)
        if not isinstance(loaded, dict):
            raise WorkflowConversionError("object_info JSON must be an object.")
        return loaded
    if comfy_url:
        url = comfy_url.rstrip("/") + "/object_info"
        with urlopen(url, timeout=10) as response:
            loaded = json.loads(response.read().decode("utf-8"))
        if not isinstance(loaded, dict):
            raise WorkflowConversionError("ComfyUI /object_info response must be an object.")
        return loaded
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a ComfyUI native workflow JSON into API prompt JSON."
    )
    parser.add_argument("workflow", help="Path to a ComfyUI workflow JSON file.")
    parser.add_argument("-o", "--output", help="Output API workflow JSON path. Defaults to stdout.")
    parser.add_argument(
        "--object-info",
        help="Optional JSON saved from ComfyUI /object_info for accurate widget mapping.",
    )
    parser.add_argument(
        "--comfy-url",
        help="Optional ComfyUI base URL; fetches /object_info before converting.",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation. Default: 2.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print detected source format, prompt nodes, output nodes, and warnings to stderr.",
    )
    return parser


def _print_summary(result: ConversionResult) -> None:
    print(f"source_format: {result.source_format}", file=sys.stderr)
    print(f"prompt_node_ids: {', '.join(result.prompt_node_ids) or '-'}", file=sys.stderr)
    print(f"output_node_ids: {', '.join(result.output_node_ids) or '-'}", file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        object_info = load_object_info(args.object_info, args.comfy_url)
        result = convert_workflow(load_json(args.workflow), object_info=object_info)
        text = json.dumps(result.prompt, ensure_ascii=False, indent=args.indent)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        if args.summary:
            _print_summary(result)
        return 0
    except Exception as exc:
        print(f"comfyui_workflow2api: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

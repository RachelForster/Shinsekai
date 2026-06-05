from __future__ import annotations

import json

from tools.comfyui_workflow2api import convert_workflow, main


def test_api_prompt_passthrough_detects_nodes() -> None:
    result = convert_workflow(
        {
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "a cat"},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"images": ["8", 0]},
            },
        }
    )

    assert result.source_format == "api"
    assert result.prompt["6"]["inputs"]["text"] == "a cat"
    assert result.prompt_node_ids == ["6"]
    assert result.output_node_ids == ["9"]


def test_converts_common_native_workflow_offline() -> None:
    native = {
        "last_node_id": 6,
        "last_link_id": 5,
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["dream.safetensors"],
            },
            {
                "id": 2,
                "type": "CLIPTextEncode",
                "widgets_values": ["highres, 1girl"],
            },
            {
                "id": 3,
                "type": "CLIPTextEncode",
                "widgets_values": ["low quality"],
            },
            {
                "id": 4,
                "type": "EmptyLatentImage",
                "widgets_values": [768, 1024, 1],
            },
            {
                "id": 5,
                "type": "KSampler",
                "inputs": [
                    {"name": "model", "link": 1},
                    {"name": "positive", "link": 2},
                    {"name": "negative", "link": 3},
                    {"name": "latent_image", "link": 4},
                ],
                "widgets_values": [123, "fixed", 20, 7.5, "euler", "normal", 1.0],
            },
            {
                "id": 6,
                "type": "SaveImage",
                "inputs": [{"name": "images", "link": 5}],
                "widgets_values": ["Shinsekai"],
            },
        ],
        "links": [
            [1, 1, 0, 5, 0, "MODEL"],
            [2, 2, 0, 5, 1, "CONDITIONING"],
            [3, 3, 0, 5, 2, "CONDITIONING"],
            [4, 4, 0, 5, 3, "LATENT"],
            [5, 5, 0, 6, 0, "IMAGE"],
        ],
    }

    result = convert_workflow(native)

    assert result.source_format == "native"
    assert result.prompt["1"]["inputs"]["ckpt_name"] == "dream.safetensors"
    assert result.prompt["2"]["inputs"]["text"] == "highres, 1girl"
    assert result.prompt["4"]["inputs"] == {"width": 768, "height": 1024, "batch_size": 1}
    assert result.prompt["5"]["inputs"]["model"] == ["1", 0]
    assert result.prompt["5"]["inputs"]["positive"] == ["2", 0]
    assert result.prompt["5"]["inputs"]["negative"] == ["3", 0]
    assert result.prompt["5"]["inputs"]["latent_image"] == ["4", 0]
    assert result.prompt["5"]["inputs"]["seed"] == 123
    assert result.prompt["5"]["inputs"]["steps"] == 20
    assert result.prompt["5"]["inputs"]["cfg"] == 7.5
    assert result.prompt["5"]["inputs"]["sampler_name"] == "euler"
    assert result.prompt["5"]["inputs"]["scheduler"] == "normal"
    assert result.prompt["5"]["inputs"]["denoise"] == 1.0
    assert result.prompt["6"]["inputs"]["images"] == ["5", 0]
    assert result.prompt["6"]["inputs"]["filename_prefix"] == "Shinsekai"
    assert result.prompt_node_ids == ["2", "3"]
    assert result.output_node_ids == ["6"]
    assert any("fixed" in warning for warning in result.warnings)


def test_uses_object_info_for_custom_widget_mapping() -> None:
    native = {
        "nodes": [
            {
                "id": 10,
                "type": "CustomPromptNode",
                "widgets_values": ["hello", 0.25],
            }
        ],
        "links": [],
    }
    object_info = {
        "CustomPromptNode": {
            "input": {
                "required": {
                    "prompt": ["STRING", {"default": ""}],
                    "weight": ["FLOAT", {"default": 1.0}],
                }
            }
        }
    }

    result = convert_workflow(native, object_info=object_info)

    assert result.prompt["10"]["inputs"] == {"prompt": "hello", "weight": 0.25}


def test_cli_writes_converted_workflow(tmp_path) -> None:
    source = tmp_path / "workflow.json"
    output = tmp_path / "workflow.api.json"
    source.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": 1,
                        "type": "CLIPTextEncode",
                        "widgets_values": ["prompt"],
                    }
                ],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    assert main([str(source), "-o", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "1": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "prompt"},
        }
    }

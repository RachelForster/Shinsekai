from __future__ import annotations

from types import SimpleNamespace

import pytest

from frontend_bridge_core.model_assets import (
    configured_model_values,
    parse_model_asset_request,
)


def test_model_asset_request_parser_projects_http_fields() -> None:
    request = parse_model_asset_request(
        {
            "assetId": "asr.faster-whisper",
            "configured": False,
            "modelName": "small",
        }
    )

    assert request.asset_id == "asr.faster-whisper"
    assert request.configured is False
    assert request.variant == "small"


def test_model_asset_request_parser_projects_direct_repo_fields() -> None:
    request = parse_model_asset_request(
        {
            "repoId": "  BAAI/bge-m3  ",
            "revision": "  v1.0  ",
            "title": "  BGE M3  ",
        }
    )

    assert request.asset_id == ""
    assert request.repo_id == "BAAI/bge-m3"
    assert request.revision == "v1.0"
    assert request.title == "BGE M3"
    assert request.configured is False


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        ({"assetId": "asr.faster-whisper", "configured": "true"}, "configured must be a boolean"),
        ({"repoId": 123}, "repoId must be a string"),
        ({"repoId": "BAAI/bge-m3", "revision": 123}, "revision must be a string"),
        ({"repoId": "BAAI/bge-m3", "title": ["bad"]}, "title must be a string"),
    ],
)
def test_model_asset_request_parser_rejects_invalid_field_types(
    payload: dict[str, object], expected_message: str
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        parse_model_asset_request(payload)


def test_configured_model_values_reads_asr_and_perception_configs() -> None:
    state = SimpleNamespace(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(
                system_config=SimpleNamespace(asr_whisper_model_size="large-v3"),
                api_config=SimpleNamespace(perception_model="Qwen/Qwen2.5-VL-3B-Instruct"),
            )
        )
    )

    assert configured_model_values(state) == {
        "asr.faster-whisper": "large-v3",
        "perception.vlm": "Qwen/Qwen2.5-VL-3B-Instruct",
    }


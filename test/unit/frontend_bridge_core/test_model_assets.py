from __future__ import annotations

import pytest

from frontend_bridge_core.model_assets import parse_model_asset_request


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


def test_model_asset_request_parser_rejects_non_boolean_configured() -> None:
    with pytest.raises(ValueError, match="configured must be a boolean"):
        parse_model_asset_request(
            {
                "assetId": "asr.faster-whisper",
                "configured": "true",
            }
        )

from types import SimpleNamespace

from application.media.effects import EffectExportResult, EffectOperation
from frontend_bridge_core.effects import effect_response_payload, parse_effect_request


def test_parse_effect_request_copies_body_and_applies_route_name() -> None:
    body = {"audioTags": "hit"}

    request = parse_effect_request(EffectOperation.DELETE, body, name="Impact")

    assert request.operation is EffectOperation.DELETE
    assert request.payload == {"audioTags": "hit", "name": "Impact"}
    assert body == {"audioTags": "hit"}


def test_effect_export_result_keeps_existing_http_shape() -> None:
    assert effect_response_payload(EffectExportResult("output/Impact.ef")) == {
        "downloadUrl": "/api/download?path=output/Impact.ef",
        "path": "output/Impact.ef",
    }


def test_non_export_results_pass_through() -> None:
    result = SimpleNamespace(name="Impact")
    assert effect_response_payload(result) is result

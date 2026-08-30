from application.backgrounds import BackgroundExportResult
from application.characters import CharacterExportResult
from frontend_bridge_core.backgrounds import background_response_payload
from frontend_bridge_core.characters import character_response_payload


def test_background_export_result_is_projected_to_http_download_url() -> None:
    assert background_response_payload(
        BackgroundExportResult(path="output/Room.bg")
    ) == {
        "downloadUrl": "/api/download?path=output/Room.bg",
        "path": "output/Room.bg",
    }


def test_character_export_result_is_projected_to_http_download_url() -> None:
    assert character_response_payload(
        CharacterExportResult(path="output/Mika.char")
    ) == {
        "downloadUrl": "/api/download?path=output/Mika.char",
        "path": "output/Mika.char",
    }


def test_non_export_results_pass_through_unchanged() -> None:
    result = {"name": "Mika"}

    assert background_response_payload(result) is result
    assert character_response_payload(result) is result

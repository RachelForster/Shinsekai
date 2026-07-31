from types import SimpleNamespace

import pytest

from frontend_bridge_core.routes.api import (
    FrontendBridgeHandler,
    _decode_url_component_once,
    _parse_query,
    _query_value,
)


def test_path_query_is_decoded_exactly_once():
    query = _parse_query("path=data%2Fbackgrounds%2F100%252Fready.png")

    assert _query_value(query, "path") == "data/backgrounds/100%2Fready.png"


def test_single_encoded_traversal_remains_visible_to_path_validation():
    query = _parse_query("path=data%2F..%2Fsecret.txt")

    assert _query_value(query, "path") == "data/../secret.txt"


def test_literal_percent_escape_filename_resolves_without_retargeting(tmp_path):
    project = tmp_path / "project"
    literal = project / "data/backgrounds/100%2Fready.png"
    literal.parent.mkdir(parents=True)
    literal.write_bytes(b"png")
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(
        state=SimpleNamespace(project_root_dir=project.as_posix()),
    )
    query = _parse_query("path=data%2Fbackgrounds%2F100%252Fready.png")

    target = handler._resolve_media_path(_query_value(query, "path"))

    assert target == literal


@pytest.mark.parametrize("raw", ("path=bad%escape", "path=%FF"))
def test_query_rejects_malformed_percent_or_utf8_encoding(raw):
    with pytest.raises((UnicodeDecodeError, ValueError)):
        _parse_query(raw)


def test_url_path_component_is_decoded_exactly_once():
    assert _decode_url_component_once("/assets/100%252Fready.js") == (
        "/assets/100%2Fready.js"
    )

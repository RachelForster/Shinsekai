from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from frontend_bridge_core.routes.file_transport import (
    FileTransport,
    RangeNotSatisfiable,
    dispatch_file_request,
)


@pytest.mark.parametrize(
    ("header", "file_size", "expected"),
    [
        (None, 100, None),
        ("items=0-10", 100, None),
        ("bytes=0-9", 100, (0, 9)),
        ("bytes=10-", 100, (10, 99)),
        ("bytes=-20", 100, (80, 99)),
        ("bytes=90-120", 100, (90, 99)),
    ],
)
def test_byte_range_parsing_remains_stable(
    header: str | None,
    file_size: int,
    expected: tuple[int, int] | None,
) -> None:
    assert FileTransport.parse_byte_range(header, file_size) == expected


def test_out_of_bounds_byte_range_is_rejected() -> None:
    with pytest.raises(RangeNotSatisfiable):
        FileTransport.parse_byte_range("bytes=100-120", 100)


def test_unknown_api_path_is_not_served_by_spa_fallback() -> None:
    class Handler:
        def _try_send_frontend(self, _path: str, *, send_body: bool = True) -> bool:
            raise AssertionError("API paths must not reach the frontend fallback")

    assert (
        dispatch_file_request(
            Handler(),
            "/api/not-registered",
            "",
            send_body=True,
        )
        is False
    )


def test_history_voice_file_is_served_by_file_transport(monkeypatch) -> None:
    handler = Mock()
    monkeypatch.setattr(
        "frontend_bridge_core.routes.file_transport._chat_voice_source",
        lambda _state, _voice_id, _index: Path("voice.wav"),
    )

    assert dispatch_file_request(
        handler,
        "/api/chat/history-voice-file",
        "voiceId=abc&segment=0",
        send_body=True,
    )
    handler._require_authorized_media_read.assert_called_once_with()
    handler._send_local_file.assert_called_once_with(Path("voice.wav"), send_body=True)

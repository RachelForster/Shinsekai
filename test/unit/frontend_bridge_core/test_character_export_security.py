from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from frontend_bridge_core.routes.api import FrontendBridgeHandler


def _export_handler(name: str) -> tuple[FrontendBridgeHandler, list[tuple[object, object]]]:
    character = SimpleNamespace(name=name)
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(
        state=SimpleNamespace(
            config_manager=SimpleNamespace(
                get_character_by_name=lambda requested: character
                if requested == name
                else None
            )
        )
    )
    handler.path = "/api/characters/export"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: {"name": name}
    handler._log_request_exception = lambda _error: None
    responses: list[tuple[object, object]] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: responses.append(
        (payload, status)
    )
    handler._send_exception_json = lambda error: responses.append((error, None))
    return handler, responses


def test_character_export_writes_only_below_output_root(tmp_path, monkeypatch):
    exported: list[Path] = []
    handler, responses = _export_handler("安全角色")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "frontend_bridge_core.routes.transfer_routes._as_character_config",
        lambda character: character,
    )
    monkeypatch.setattr(
        "tools.file_util.export_character",
        lambda _characters, output, *, open_folder: exported.append(Path(output)),
    )

    handler.do_POST()

    expected = (tmp_path / "output" / "安全角色.char").resolve(strict=False)
    assert exported == [expected]
    assert responses == [
        (
            {
                "downloadUrl": "/api/download?path=output/安全角色.char",
                "path": "output/安全角色.char",
            },
            HTTPStatus.OK,
        )
    ]


def test_character_export_rejects_path_components_before_file_io(tmp_path, monkeypatch):
    exported: list[Path] = []
    handler, responses = _export_handler("../outside")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "tools.file_util.export_character",
        lambda _characters, output, *, open_folder: exported.append(Path(output)),
    )

    handler.do_POST()

    assert exported == []
    assert len(responses) == 1
    error, status = responses[0]
    assert status is None
    assert isinstance(error, ValueError)
    assert "path separators" in str(error)
    assert not (tmp_path / "outside.char").exists()

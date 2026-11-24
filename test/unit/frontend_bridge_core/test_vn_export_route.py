from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from application.chat.export_vn.export_playable_vn import PlayableVnExportOutcome
from frontend_bridge_core.routes.chat_routes import CHAT_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, Router


def _match_export_route(state: object, body: dict) -> tuple[ApiRequest, object]:
    router = Router(list(CHAT_ROUTES))
    matched = router.match("POST", "/api/chat/export-vn")
    assert matched is not None
    req = ApiRequest(
        state=state,
        method="POST",
        path="/api/chat/export-vn",
        query={},
        params=matched.params,
        body=body,
    )
    return req, matched.route


def test_export_vn_route_projects_zip_download_url(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_export(_state, export_req):
        captured["req"] = export_req
        return PlayableVnExportOutcome(
            path="output/vn_exports/demo.zip",
            is_project_relative=True,
            format="zip",
            entry_count=5,
            asset_count=3,
            voice_count=2,
            transcoded_voice_count=2,
            skipped_non_static_sprites=0,
            total_bytes=12345,
            index_html_bytes=2048,
            warnings=(),
        )

    monkeypatch.setattr("frontend_bridge_core.routes.chat_routes.export_playable_vn", fake_export)
    req, route = _match_export_route(
        SimpleNamespace(project_root_dir=str(tmp_path)),
        {
            "conversationId": "c1",
            "selectedEntryIds": ["history-0", "history-2"],
            "expectedSessionId": "sess-9",
            "selectedEntryAnchors": [{"id": "history-0", "role": "user", "dialogId": "", "text": "You: Hi"}],
            "title": "Demo",
            "outputFormat": "zip",
            "includeVoices": True,
            "transcodeMp3": True,
        },
    )
    res = route.handler(req)
    assert res.data["downloadUrl"] == "/api/download?path=output/vn_exports/demo.zip"
    assert res.data["entryCount"] == 5
    assert captured["req"].conversation_id == "c1"
    assert captured["req"].selected_entry_ids == ("history-0", "history-2")
    assert captured["req"].expected_session_id == "sess-9"
    assert captured["req"].selected_entry_anchors == (
        {"id": "history-0", "role": "user", "dialogId": "", "text": "You: Hi"},
    )


def test_export_vn_route_omits_download_url_for_directory_and_opens_folder(monkeypatch, tmp_path: Path) -> None:
    opened_paths: list[Path] = []

    def fake_export(_state, _export_req):
        return PlayableVnExportOutcome(
            path="output/vn_exports/demo-dir",
            is_project_relative=True,
            format="directory",
            entry_count=3,
            asset_count=1,
            voice_count=0,
            transcoded_voice_count=0,
            skipped_non_static_sprites=1,
            total_bytes=4096,
            index_html_bytes=1800,
            warnings=("skipped_non_static_sprites",),
        )

    monkeypatch.setattr("frontend_bridge_core.routes.chat_routes.export_playable_vn", fake_export)
    monkeypatch.setattr("tools.file_util._open_export_folder", lambda p: opened_paths.append(Path(p)) or True)

    req, route = _match_export_route(
        SimpleNamespace(project_root_dir=str(tmp_path)),
        {"outputFormat": "directory", "openFolder": True},
    )
    res = route.handler(req)
    assert "downloadUrl" not in res.data
    assert res.data["folderOpened"] is True
    assert res.data["warnings"] == ["skipped_non_static_sprites"]
    assert opened_paths == [(tmp_path / "output/vn_exports/demo-dir/index.html").resolve()]

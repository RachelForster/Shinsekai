"""Route contract and behavior tests for /api/novel/* endpoints."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.llm.template_generator import TemplateGenerator
from application.novel_theater import (
    materialize_novel_session_binding,
    rollback_novel_session_binding,
)
from config.config_manager import ConfigManager
from config.schema import ApiConfig, AppConfig, SystemConfig
from core.chat_history.sqlite_session_store import close_all_session_stores
from core.chat_history.storage import chat_history_session_dir
from frontend_bridge_core.routes.novel_routes import NOVEL_ROUTES
from frontend_bridge_core.routes.router import ApiRequest, BodyKind, Router
from sdk.exception.types import AppError


def _contracts() -> set[tuple[str, str]]:
    return {(method, route.pattern) for route in NOVEL_ROUTES for method in route.methods}


def _make_state(tmp_path: Path) -> SimpleNamespace:
    cfg = object.__new__(ConfigManager)
    cfg._config = AppConfig(
        characters=[],
        background_list=[],
        api_config=ApiConfig(),
        system_config=SystemConfig(ui_language="zh_CN"),
    )
    cfg._characters_revision = ""
    cfg._API_CONFIG_PATH = Path("nonexistent-test-api.yaml")
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    hist_dir = tmp_path / "chat_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        project_root_dir=str(tmp_path),
        template_dir_path=str(tpl_dir),
        history_dir=str(hist_dir),
        config_manager=cfg,
        template_generator=TemplateGenerator(),
        chat_session={},
    )


def test_novel_route_contracts() -> None:
    assert _contracts() == {
        ("GET", "/api/novel/documents"),
        ("POST", "/api/novel/documents/import"),
        ("GET", "/api/novel/documents/{doc_id}"),
        ("DELETE", "/api/novel/documents/{doc_id}"),
        ("POST", "/api/novel/documents/{doc_id}/extract-cast"),
        ("POST", "/api/novel/casting"),
        ("POST", "/api/novel/launch-payload"),
        ("POST", "/api/novel/jump-chapter"),
    }


def test_novel_document_routes_end_to_end_and_error_guards(tmp_path: Path) -> None:
    router = Router(list(NOVEL_ROUTES))
    state = _make_state(tmp_path)

    # Missing upload raises AppError("novel.document_file_required")
    import_match = router.match("POST", "/api/novel/documents/import")
    assert import_match is not None
    assert import_match.route.body_kind is BodyKind.MULTIPART
    with pytest.raises(AppError) as missing_exc:
        import_match.route.handler(
            ApiRequest(
                state=state,
                method="POST",
                path="/api/novel/documents/import",
                query={},
                params=import_match.params,
                body={},
                uploads=SimpleNamespace(paths=()),
            )
        )
    assert missing_exc.value.error_code == "novel.document_file_required"

    # Multipart import TXT
    src_file = tmp_path / "demo_book.txt"
    src_file.write_text("Chapter 1 Dawn\n\nA quiet morning at the station.", encoding="utf-8")
    imported = import_match.route.handler(
        ApiRequest(
            state=state,
            method="POST",
            path="/api/novel/documents/import",
            query={},
            params=import_match.params,
            body={},
            uploads=SimpleNamespace(paths=(src_file,)),
        )
    )
    doc_id = imported.data["document"]["manifest"]["docId"]

    # List & get detail
    list_match = router.match("GET", "/api/novel/documents")
    assert list_match is not None
    listed = list_match.route.handler(
        ApiRequest(
            state=state,
            method="GET",
            path="/api/novel/documents",
            query={},
            params={},
            body={},
        )
    )
    assert len(listed.data["documents"]) == 1

    get_match = router.match("GET", f"/api/novel/documents/{doc_id}")
    assert get_match is not None
    detail = get_match.route.handler(
        ApiRequest(
            state=state,
            method="GET",
            path=f"/api/novel/documents/{doc_id}",
            query={},
            params=get_match.params,
            body={},
        )
    )
    assert detail.data["document"]["manifest"]["docId"] == doc_id
    assert router.match("GET", "/api/novel/documents/../../etc") is None

    # Launch payload pure dialogue
    launch_match = router.match("POST", "/api/novel/launch-payload")
    assert launch_match is not None
    launched = launch_match.route.handler(
        ApiRequest(
            state=state,
            method="POST",
            path="/api/novel/launch-payload",
            query={},
            params={},
            body={"docId": doc_id, "casting": []},
        )
    )
    payload = launched.data["payload"]
    assert payload["behaviorId"] == "novel_theater"
    assert payload["nameMode"] == "actor"
    assert payload["system"]
    assert payload["showInitialSprite"] is False

    launched_story = launch_match.route.handler(
        ApiRequest(
            state=state,
            method="POST",
            path="/api/novel/launch-payload",
            query={},
            params={},
            body={"docId": doc_id, "casting": [], "nameMode": "story"},
        )
    )
    assert launched_story.data["payload"]["nameMode"] == "story"

    # Preparing launch payload alone must not lock the document on disk.
    session_dir = chat_history_session_dir(payload["historyPath"])
    assert not (session_dir / "document-binding.json").exists()

    # Delete rejects once binding is materialized, and succeeds again after rollback.
    handle = materialize_novel_session_binding(state, payload, payload["historyPath"])
    assert (session_dir / "document-binding.json").is_file()
    del_match = router.match("DELETE", f"/api/novel/documents/{doc_id}")
    assert del_match is not None
    with pytest.raises(AppError) as in_use:
        del_match.route.handler(
            ApiRequest(
                state=state,
                method="DELETE",
                path=f"/api/novel/documents/{doc_id}",
                query={},
                params=del_match.params,
                body={},
            )
        )
    assert in_use.value.error_code == "novel.document_in_use"

    rollback_novel_session_binding(handle)
    close_all_session_stores()
    deleted = del_match.route.handler(
        ApiRequest(
            state=state,
            method="DELETE",
            path=f"/api/novel/documents/{doc_id}",
            query={},
            params=del_match.params,
            body={},
        )
    )
    assert deleted.data == {"ok": True, "docId": doc_id}


def test_jump_chapter_and_casting_validation(monkeypatch) -> None:
    router = Router(list(NOVEL_ROUTES))
    captured: list[dict] = []

    monkeypatch.setattr(
        "frontend_bridge_core.routes.novel_routes._handle_chat_command",
        lambda _state, cmd: captured.append(cmd),
    )
    monkeypatch.setattr(
        "frontend_bridge_core.routes.novel_routes._chat_snapshot",
        lambda _state: {"status": "idle"},
    )
    cast_calls: list[str | None] = []
    monkeypatch.setattr(
        "frontend_bridge_core.routes.novel_routes.save_novel_casting",
        lambda _state, cid, bindings, name_mode=None: (
            cast_calls.append(name_mode),
            {"id": cid, "castEntries": bindings, "novelNameMode": name_mode or "story"},
        )[1],
    )

    jump_match = router.match("POST", "/api/novel/jump-chapter")
    assert jump_match is not None
    with pytest.raises(AppError) as bad_chap:
        jump_match.route.handler(
            ApiRequest(
                state=SimpleNamespace(),
                method="POST",
                path="/api/novel/jump-chapter",
                query={},
                params={},
                body={"chapterIndex": -1, "expectedStateVersion": 1},
            )
        )
    assert bad_chap.value.error_code == "novel.invalid_chapter"

    resp = jump_match.route.handler(
        ApiRequest(
            state=SimpleNamespace(),
            method="POST",
            path="/api/novel/jump-chapter",
            query={},
            params={},
            body={"chapterIndex": 3, "expectedStateVersion": 7, "commandId": "cmd-7"},
        )
    )
    assert resp.data == {"ok": True, "chat": {"status": "idle"}}
    assert captured[0] == {
        "type": "behavior-command",
        "payload": {
            "commandId": "cmd-7",
            "action": "jump_chapter",
            "expectedStateVersion": 7,
            "payload": {"chapterIndex": 3},
        },
    }

    cast_match = router.match("POST", "/api/novel/casting")
    assert cast_match is not None
    cast_resp = cast_match.route.handler(
        ApiRequest(
            state=SimpleNamespace(),
            method="POST",
            path="/api/novel/casting",
            query={},
            params={},
            body={"conversationId": "c1", "bindings": [{"sourceName": "Alice"}]},
        )
    )
    assert cast_resp.data["conversation"]["id"] == "c1"
    assert cast_calls[-1] is None

    cast_actor_resp = cast_match.route.handler(
        ApiRequest(
            state=SimpleNamespace(),
            method="POST",
            path="/api/novel/casting",
            query={},
            params={},
            body={
                "conversationId": "c1",
                "bindings": [{"sourceName": "Lin", "targetCharacter": "Alice"}],
                "nameMode": "actor",
            },
        )
    )
    assert cast_actor_resp.data["conversation"]["novelNameMode"] == "actor"
    assert cast_calls[-1] == "actor"

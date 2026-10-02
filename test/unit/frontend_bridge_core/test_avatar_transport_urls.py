from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest

from application.chat.ui_updates import StreamingUIUpdateManager
from application.chat.session_metadata import chat_session_media
from frontend_bridge_core.chat_stream import ChatStreamService
from frontend_bridge_core.transport.ws_client import WSClientSink


@pytest.mark.parametrize("token_key", ["shinsekai_bridge_token", "token"])
def test_ws_producer_uses_same_avatar_route_as_bridge(tmp_path, token_key):
    model = tmp_path / "模型" / "Haru.model3.json"
    state = model.parent / "states" / "微笑.json"
    sink = WSClientSink(f"ws://127.0.0.1:8788/ws?{token_key}=test%2Btoken")
    service = ChatStreamService(host="127.0.0.1", bridge_port=8787, auth_token="test+token")

    for path in (model, state):
        url = sink.avatar_url(str(model), str(path))
        assert url == service.avatar_url(str(model), str(path))
        parsed = urlsplit(url)
        assert parsed.netloc == "127.0.0.1:8787"
        assert parsed.path == "/api/avatar/file"
        assert parse_qs(parsed.query) == {
            "model_path": [str(model)],
            "path": [path.relative_to(model.parent).as_posix()],
            "shinsekai_bridge_token": ["test+token"],
        }


def test_ws_producer_rejects_avatar_path_outside_model_directory(tmp_path):
    sink = WSClientSink("ws://127.0.0.1:8788/ws")
    with pytest.raises(ValueError):
        sink.avatar_url(str(tmp_path / "model" / "Haru.model3.json"), str(tmp_path / "outside.json"))


def test_stage_model_event_from_real_producer_never_uses_image_media_route(tmp_path, monkeypatch):
    model = tmp_path / "Haru.model3.json"
    state = tmp_path / "states" / "smile.json"
    character = SimpleNamespace(
        avatar_type="l2d", sprite_scale=1.25,
        avatars={"l2d": {"model_path": str(model), "sprites": [{"path": str(state)}]}},
    )
    sink = WSClientSink("ws://127.0.0.1:8788/ws?token=test-token")
    monkeypatch.setattr(sink, "_ensure_worker", lambda: None)
    with patch("application.chat.ui_updates.get_character_by_name", return_value=character):
        StreamingUIUpdateManager(sink, resource_urls=sink.resource_urls).update_sprite("Haru", 0)
    event = sink._peek_event()
    assert event["type"] == "sprite.show"
    assert event["avatarType"] == "l2d"
    for key in ("url", "modelUrl"):
        assert urlsplit(event[key]).path == "/api/avatar/file"


def test_static_media_route_is_unchanged():
    sink = WSClientSink("ws://127.0.0.1:8788/ws?token=test-token")
    url = sink.media_url("data/sprite/idle.png")
    assert urlsplit(url).path == "/api/media"
    assert parse_qs(urlsplit(url).query)["path"] == ["data/sprite/idle.png"]
    assert sink.media_url("https://example.com/idle.png") == "https://example.com/idle.png"


@pytest.mark.parametrize("avatar_type", ["static", "demo"])
def test_initial_stage_snapshot_respects_selected_avatar_bank(tmp_path, avatar_type):
    model = tmp_path / "Haru.model3.json"
    sprite = tmp_path / "states" / "smile.json"
    character = SimpleNamespace(
        name="Haru", avatar_type=avatar_type, sprite_scale=1.2,
        sprites=[{"path": "static.png"}],
        avatars={"demo": {"model_path": str(model), "sprites": [{"path": str(sprite)}]}},
    )
    state = SimpleNamespace(
        chat_session={"characterName": "Haru"},
        config_manager=SimpleNamespace(
            config=SimpleNamespace(characters=[character]),
            get_character_by_name=lambda name: character,
        ),
        resource_urls=ChatStreamService(host="127.0.0.1", bridge_port=8787, auth_token="test-token").resource_urls,
    )
    background, name, sprites = chat_session_media(state)
    assert background == ""
    assert name == "Haru"
    assert len(sprites) == 1
    assert sprites[0]["avatarType"] == avatar_type
    assert sprites[0]["scale"] == 1.2
    if avatar_type == "demo":
        assert parse_qs(urlsplit(sprites[0]["path"]).query)["path"] == ["states/smile.json"]
        assert urlsplit(sprites[0]["modelUrl"]).path == "/api/avatar/file"
    else:
        assert urlsplit(sprites[0]["path"]).path == "/api/media"
        assert parse_qs(urlsplit(sprites[0]["path"]).query)["path"] == ["static.png"]
        assert sprites[0]["modelUrl"] == ""


def test_presenter_rejects_incomplete_resource_contract():
    with pytest.raises(TypeError, match="both media and model"):
        StreamingUIUpdateManager(SimpleNamespace(emit=lambda event: None),
                                 resource_urls=SimpleNamespace(media_url=lambda path: path))

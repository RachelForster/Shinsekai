from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from application.chat import presentation


class _SystemConfig:
    background_path = "old-bg"
    bgm_path = "old-bgm"

    def model_copy(self, *, deep: bool):
        assert deep is True
        clone = _SystemConfig()
        clone.background_path = self.background_path
        clone.bgm_path = self.bgm_path
        return clone


class _Config:
    def __init__(self) -> None:
        self.config = SimpleNamespace(system_config=_SystemConfig())
        self.saved = 0

    def save_system_config(self) -> None:
        self.saved += 1


def test_load_presentation_assets_handles_transparent_and_selected_background() -> None:
    config = SimpleNamespace(
        get_background_by_name=lambda _name: SimpleNamespace(
            sprites=[{"path": "bg.png"}],
            bgm_list=["bgm.mp3"],
        )
    )

    selected = presentation.load_presentation_assets(config, "room")
    transparent = presentation.load_presentation_assets(config, "")

    assert selected.background_sprites == [{"path": "bg.png"}]
    assert selected.bgm_paths == ["bgm.mp3"]
    assert selected.transparent is False
    assert transparent.background_sprites == []
    assert transparent.bgm_paths == []
    assert transparent.transparent is True


def test_prepare_initial_presentation_restores_media_and_falls_back_to_sprite(
    monkeypatch,
) -> None:
    config = _Config()
    ui = SimpleNamespace(
        post_background=Mock(),
        switch_bgm=Mock(),
        post_dialog_html=Mock(),
        post_options=Mock(),
        post_notification=Mock(),
    )
    publish_tree = Mock()
    display_sprite = Mock()
    monkeypatch.setattr(
        presentation,
        "restore_session_presentation",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(presentation, "display_initial_sprite", display_sprite)
    monkeypatch.setattr(presentation, "get_history", lambda: [])
    assets = presentation.ChatPresentationAssets(
        background_sprites=[{"path": "bg.png"}],
        bgm_paths=["bgm.mp3"],
        transparent=False,
    )

    presentation.prepare_initial_presentation(
        messages=[],
        config=config,
        ui_updates=ui,
        presentation_queue=object(),
        assets=assets,
        initial_sprite_path="sprite.png",
        welcome_html="welcome",
        initial_option="start",
        ready_notification="ready",
        publish_branch_tree=publish_tree,
        translate=lambda key, **_kwargs: key,
    )

    assert config.config.system_config.background_path == "bg.png"
    assert config.config.system_config.bgm_path == "bgm.mp3"
    assert config.saved == 1
    ui.post_background.assert_called_once_with("bg.png")
    ui.switch_bgm.assert_called_once_with("bgm.mp3")
    ui.post_dialog_html.assert_called_once_with(
        "welcome",
        is_system=True,
        color="#84C2D5",
    )
    ui.post_options.assert_called_once_with(["start"])
    ui.post_notification.assert_called_once_with("ready")
    publish_tree.assert_called_once_with()
    display_sprite.assert_called_once_with(
        "sprite.png",
        config=config,
        ui_updates=ui,
    )

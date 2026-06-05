from pathlib import Path
from queue import Queue
from types import SimpleNamespace

from core.sprite import chat_ui_service
from core.sprite.initial_sprite import (
    display_initial_sprite,
    find_character_sprite_by_path,
)


class _Window:
    def __init__(self):
        self.backgrounds = []

    def setBackgroundImage(self, path):
        self.backgrounds.append(path)


def _config(characters=None, bgm_path="", background_path=""):
    return SimpleNamespace(
        config=SimpleNamespace(
            characters=characters or [],
            system_config=SimpleNamespace(
                bgm_path=bgm_path,
                background_path=background_path,
            ),
        )
    )


def test_find_character_sprite_by_path_matches_relative_and_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sprite_rel = Path("data/sprite/nanami/idle.webp")
    sprite_abs = tmp_path / sprite_rel
    character = SimpleNamespace(
        name="七海千秋",
        sprites=[SimpleNamespace(path=sprite_rel.as_posix())],
    )

    assert find_character_sprite_by_path(
        _config(characters=[character]),
        sprite_abs.as_posix(),
    ) == ("七海千秋", 0)


def test_display_initial_sprite_prefers_character_sprite_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    character = SimpleNamespace(
        name="七海千秋",
        sprites=[{"path": "data/sprite/nanami/idle.webp"}],
    )
    calls = []
    ui_updates = SimpleNamespace(
        update_sprite=lambda name, index: calls.append(("config", name, index)),
        update_sprite_from_path=lambda *args, **kwargs: calls.append(
            ("path", args, kwargs)
        ),
    )

    assert display_initial_sprite(
        "data/sprite/nanami/idle.webp",
        config=_config(characters=[character]),
        ui_updates=ui_updates,
    )

    assert calls == [("config", "七海千秋", 0)]


def test_restore_session_ui_applies_background_without_messages():
    queue = Queue()
    window = _Window()

    restored = chat_ui_service.restore_session_ui(
        [],
        audio_path_queue=queue,
        window=window,
        config=_config(bgm_path="data/bgm/theme.ogg", background_path="data/bg/classroom.webp"),
        tr_i18n=lambda key, **kwargs: key,
    )

    assert restored is False
    assert window.backgrounds == ["data/bg/classroom.webp"]
    bgm = queue.get_nowait()
    assert bgm.name == "bgm"
    assert bgm.audio_path == "data/bgm/theme.ogg"


def test_restore_session_ui_reports_restored_character_sprite(monkeypatch):
    queue = Queue()
    window = _Window()
    monkeypatch.setattr(
        chat_ui_service,
        "extract_valid_dialog_from_messages",
        lambda messages: [
            {"character_name": "七海千秋", "speech": "你好", "sprite": "1"},
        ],
    )

    restored = chat_ui_service.restore_session_ui(
        [{"role": "assistant"}],
        audio_path_queue=queue,
        window=window,
        config=_config(),
        tr_i18n=lambda key, **kwargs: key,
    )

    assert restored is True
    output = queue.get_nowait()
    assert output.name == "七海千秋"
    assert output.asset_id == "1"

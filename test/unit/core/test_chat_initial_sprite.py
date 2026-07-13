import os
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest

from core.sprite import chat_ui_service
from core.sprite.initial_sprite import (
    display_initial_sprite,
    find_character_sprite_by_path,
    initial_sprite_path_for_characters,
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


def test_find_character_sprite_by_path_uses_host_case_semantics_and_normalizes_slashes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    character = SimpleNamespace(
        name="Nanami",
        sprites=[SimpleNamespace(path="C:/Sprites/Nanami/Idle.PNG")],
    )

    matched = find_character_sprite_by_path(
        _config(characters=[character]),
        "c:\\sprites\\nanami\\idle.png",
    )
    expected = ("Nanami", 0) if os.path.normcase("A") == os.path.normcase("a") else None
    assert matched == expected


def test_find_character_sprite_by_path_preserves_case_distinct_files_on_sensitive_hosts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    characters = [
        SimpleNamespace(name="Upper", sprites=[SimpleNamespace(path="sprites/Face.png")]),
        SimpleNamespace(name="Lower", sprites=[SimpleNamespace(path="sprites/face.png")]),
    ]

    matched = find_character_sprite_by_path(_config(characters=characters), "sprites/face.png")
    expected = ("Upper", 0) if os.path.normcase("A") == os.path.normcase("a") else ("Lower", 0)
    assert matched == expected


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


def test_initial_sprite_path_rejects_sprite_owned_by_unselected_character(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nanami = SimpleNamespace(
        name="七海千秋",
        sprites=[SimpleNamespace(path="data/sprite/nanami/idle.webp")],
    )
    junko = SimpleNamespace(
        name="江之岛盾子",
        sprites=[SimpleNamespace(path="data/sprite/junko/idle.webp")],
    )
    config = _config(characters=[nanami, junko])
    config.get_character_by_name = lambda name: next(
        (character for character in config.config.characters if character.name == name),
        None,
    )

    assert initial_sprite_path_for_characters(
        config,
        "data/sprite/junko/idle.webp",
        ["七海千秋"],
    ) == "data/sprite/nanami/idle.webp"


def test_initial_sprite_path_preserves_selected_or_custom_sprite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nanami = SimpleNamespace(
        name="七海千秋",
        sprites=[SimpleNamespace(path="data/sprite/nanami/idle.webp")],
    )
    config = _config(characters=[nanami])
    config.get_character_by_name = lambda name: nanami if name == nanami.name else None

    assert initial_sprite_path_for_characters(
        config,
        "data/sprite/nanami/idle.webp",
        ["七海千秋"],
    ) == "data/sprite/nanami/idle.webp"
    assert initial_sprite_path_for_characters(
        config,
        "D:/custom/portrait.png",
        ["七海千秋"],
    ) == "D:/custom/portrait.png"


@pytest.mark.parametrize(
    ("raw_path", "selected_names", "expected"),
    [
        ("", ["Nanami"], "C:/Sprites/Nanami/Idle.PNG"),
        ("c:\\sprites\\nanami\\idle.png", ["Nanami"], "c:\\sprites\\nanami\\idle.png"),
        (
            "C:/SPRITES/JUNKO/IDLE.png",
            ["Nanami"],
            "C:/Sprites/Nanami/Idle.PNG"
            if os.path.normcase("A") == os.path.normcase("a")
            else "C:/SPRITES/JUNKO/IDLE.png",
        ),
        ("C:/Sprites/Junko/Idle.PNG", ["Junko"], "C:/Sprites/Junko/Idle.PNG"),
        ("D:/external/custom.png", ["Nanami"], "D:/external/custom.png"),
        ("C:/Sprites/Nanami/Idle.PNG", [], ""),
        ("C:/Sprites/Nanami/Idle.PNG", [None, {}, " "], ""),
    ],
)
def test_initial_sprite_path_uses_the_same_owner_compatibility_rules(
    tmp_path,
    monkeypatch,
    raw_path,
    selected_names,
    expected,
):
    monkeypatch.chdir(tmp_path)
    characters = [
        SimpleNamespace(name="Nanami", sprites=[SimpleNamespace(path="C:/Sprites/Nanami/Idle.PNG")]),
        SimpleNamespace(name="Junko", sprites=[SimpleNamespace(path="C:/Sprites/Junko/Idle.PNG")]),
    ]
    config = _config(characters=characters)
    config.get_character_by_name = lambda name: next(
        (character for character in characters if character.name == name),
        None,
    )

    assert initial_sprite_path_for_characters(config, raw_path, selected_names) == expected


def test_initial_sprite_path_preserves_unknown_path_without_characters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = _config(characters=[])
    config.get_character_by_name = lambda _name: None

    assert initial_sprite_path_for_characters(config, "D:/external/custom.png", []) == "D:/external/custom.png"


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

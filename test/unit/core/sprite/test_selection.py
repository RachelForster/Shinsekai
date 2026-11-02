from pathlib import Path
from types import SimpleNamespace

from core.sprite.selection import (
    find_character_sprite_by_path,
    resolve_initial_sprite_path,
)


def test_find_character_sprite_by_path_accepts_character_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    characters = [
        SimpleNamespace(
            name="Nanami",
            sprites=[SimpleNamespace(path="data/sprite/nanami/idle.webp")],
        )
    ]

    assert find_character_sprite_by_path(
        characters,
        (tmp_path / "data/sprite/nanami/idle.webp").as_posix(),
    ) == ("Nanami", 0)


def test_resolve_initial_sprite_path_rejects_another_character_sprite() -> None:
    characters = [
        {"name": "Nanami", "sprites": [{"path": "sprites/nanami.png"}]},
        {"name": "Junko", "sprites": [{"path": "sprites/junko.png"}]},
    ]

    assert (
        resolve_initial_sprite_path(
            characters,
            "sprites/junko.png",
            ["Nanami"],
            default_path="sprites/nanami.png",
        )
        == "sprites/nanami.png"
    )
    assert (
        resolve_initial_sprite_path(
            characters,
            "custom/portrait.png",
            ["Nanami"],
            default_path="sprites/nanami.png",
        )
        == "custom/portrait.png"
    )

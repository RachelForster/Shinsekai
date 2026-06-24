from types import SimpleNamespace

from config.character_manager import CharacterManager
from config.schema import Character


class FakeConfigManager:
    def __init__(self, characters):
        self.config = SimpleNamespace(characters=characters)
        self.save_count = 0

    def get_character_by_name(self, name):
        return next((character for character in self.config.characters if character.name == name), None)

    def save_characters_config(self):
        self.save_count += 1


def build_manager(characters):
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = FakeConfigManager(characters)
    return manager


def test_add_character_updates_existing_emotion_tags():
    character = Character(name="Mika", color="#66ccff", sprite_prefix="mika", emotion_tags="Sprite 1: old\n")
    manager = build_manager([character])

    manager.add_character(
        "Mika",
        "#66ccff",
        "mika",
        "",
        "",
        "",
        "",
        "",
        "Quiet student.",
        edit_as_name="Mika",
        emotion_tags="Sprite 1: calm\n",
    )

    assert character.emotion_tags == "Sprite 1: calm\n"
    assert manager._config_manager.save_count == 1


def test_add_character_applies_emotion_tags_to_new_character():
    manager = build_manager([])

    manager.add_character(
        "Mika",
        "#66ccff",
        "mika",
        "",
        "",
        "",
        "",
        "",
        "Quiet student.",
        emotion_tags="Sprite 1: calm\n",
    )

    assert manager._config_manager.config.characters[0].emotion_tags == "Sprite 1: calm\n"
    assert manager._config_manager.save_count == 1


def test_add_character_creates_when_edit_target_is_missing():
    manager = build_manager([])

    manager.add_character(
        "Sora",
        "#ff99aa",
        "sora",
        "",
        "",
        "",
        "",
        "",
        "New character.",
        edit_as_name="Missing",
        emotion_tags="Sprite 1: smile\n",
    )

    assert len(manager._config_manager.config.characters) == 1
    assert manager._config_manager.config.characters[0].name == "Sora"
    assert manager._config_manager.config.characters[0].emotion_tags == "Sprite 1: smile\n"
    assert manager._config_manager.save_count == 1

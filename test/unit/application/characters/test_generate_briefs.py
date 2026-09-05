from types import SimpleNamespace

import pytest

from application.characters import generate_briefs
from test.conftest import make_character


class _ConfigStore:
    def __init__(self, characters):
        self.characters = characters
        self.saved = 0

    def get_character_by_name(self, name):
        return next(
            (character for character in self.characters if character.name == name),
            None,
        )

    def save_characters_config(self):
        self.saved += 1


def test_normalize_character_brief_flattens_and_limits_text():
    raw = '"' + ("人物关系清晰\n性格坚定 " * 20) + '"'

    result = generate_briefs.normalize_character_brief(raw)

    assert "\n" not in result
    assert len(result) == generate_briefs.MAX_CHARACTER_BRIEF_LENGTH


def test_generate_character_brief_uses_name_and_setting(monkeypatch):
    captured = SimpleNamespace(system="", user="")

    def fake_chat(_config, system, user):
        captured.system = system
        captured.user = user
        return "冷静可靠，重视与米卡的约定。"

    monkeypatch.setattr(generate_briefs, "_chat", fake_chat)

    result = generate_briefs.generate_character_brief(
        object(), "奈奈美", "学生会长，与米卡是挚友。"
    )

    assert result == "冷静可靠，重视与米卡的约定。"
    assert "100" in captured.system
    assert "奈奈美" in captured.user
    assert "学生会长" in captured.user


def test_ensure_character_briefs_generates_only_missing_and_saves_once(monkeypatch):
    existing = make_character(
        name="Alice",
        character_brief="已有简介",
        character_setting="Alice full setting",
    )
    missing = make_character(name="Mika", character_setting="Mika full setting")
    store = _ConfigStore([existing, missing])

    def fake_chat(_config, _system, user):
        assert "Alice full setting" not in user
        assert "Mika full setting" in user
        return '```json\n{"briefs":[{"name":"Mika","brief":"安静敏锐，是 Alice 的重要伙伴。"}]}\n```'

    monkeypatch.setattr(generate_briefs, "_chat", fake_chat)

    characters, generated_names = generate_briefs.ensure_character_briefs(
        store,
        ["Alice", "Mika", "mika", "Missing"],
    )

    assert characters == [existing, missing]
    assert generated_names == ["Mika"]
    assert existing.character_brief == "已有简介"
    assert missing.character_brief == "安静敏锐，是 Alice 的重要伙伴。"
    assert store.saved == 1


def test_ensure_character_briefs_does_not_save_partial_results(monkeypatch):
    alice = make_character(name="Alice", character_setting="Alice setting")
    mika = make_character(name="Mika", character_setting="Mika setting")
    store = _ConfigStore([alice, mika])
    monkeypatch.setattr(
        generate_briefs,
        "_chat",
        lambda *_args: '{"briefs":[{"name":"Alice","brief":"Only Alice"}]}',
    )

    with pytest.raises(ValueError, match="Mika"):
        generate_briefs.ensure_character_briefs(store, ["Alice", "Mika"])

    assert alice.character_brief == ""
    assert mika.character_brief == ""
    assert store.saved == 0

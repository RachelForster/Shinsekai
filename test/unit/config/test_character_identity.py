from config.character_identity import ensure_character_ids, installation_id
from config.schema import Character


def test_legacy_and_duplicate_ids_are_added_without_changing_content(tmp_path):
    rows = [{"name": "A", "character_setting": "keep", "sprites": []}, {"name": "B", "id": "existing"}, {"name": "C", "id": "existing"}]
    assert ensure_character_ids(rows)
    assert len({row["id"] for row in rows}) == 3
    assert rows[0]["character_setting"] == "keep"
    assert rows[1]["id"] == "existing"
    assert not ensure_character_ids(rows)
    assert installation_id(tmp_path) == installation_id(tmp_path)


def test_character_identity_survives_rename_and_serialization():
    first = Character(name="A", color="#ffffff", sprite_prefix="a")
    data = first.model_dump(mode="json")
    data["name"] = "Renamed"
    assert Character.model_validate(data).id == first.id
    assert Character(name="A", color="#ffffff", sprite_prefix="a").id != first.id

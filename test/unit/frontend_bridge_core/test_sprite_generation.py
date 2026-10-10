from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from frontend_bridge_core.tools import _generate_sprite_prompts, _generate_sprites


def test_bridge_prompt_generation_passes_only_the_target_character_to_configured_llm(
    monkeypatch,
):
    generate = Mock(return_value=["wave", "smile"])
    updates = Mock()
    monkeypatch.setattr(
        "application.image_generation.prompts.generate_sprite_prompts", generate
    )
    monkeypatch.setattr("frontend_bridge_core.tools._update_task", updates)
    config = SimpleNamespace(
        get_character_by_name=Mock(
            return_value=SimpleNamespace(character_setting="冷静")
        )
    )
    result = _generate_sprite_prompts(
        SimpleNamespace(config_manager=config),
        "task",
        {"characterName": " Rafal ", "count": 2},
    )
    assert result == {"prompts": ["wave", "smile"]}
    config.get_character_by_name.assert_called_once_with("Rafal")
    generate.assert_called_once_with(
        config, character_name="Rafal", character_setting="冷静", count=2
    )
    assert updates.call_args.kwargs["result"] == result


def test_bridge_does_not_mark_failed_prompt_generation_as_completed(monkeypatch):
    generate = Mock(side_effect=ValueError("LLM returned no prompts"))
    updates = Mock()
    monkeypatch.setattr(
        "application.image_generation.prompts.generate_sprite_prompts", generate
    )
    monkeypatch.setattr("frontend_bridge_core.tools._update_task", updates)
    config = SimpleNamespace(
        get_character_by_name=lambda name: SimpleNamespace(character_setting="")
    )
    with pytest.raises(ValueError, match="LLM returned no prompts"):
        _generate_sprite_prompts(
            SimpleNamespace(config_manager=config), "task", {"characterName": "Rafal"}
        )
    assert all(call.kwargs["phase"] != "completed" for call in updates.call_args_list)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"characterName": "Rafal", "count": 0},
        {"characterName": "Rafal", "count": 101},
    ],
)
def test_prompt_request_validation_does_not_call_llm(monkeypatch, payload):
    generate = Mock()
    monkeypatch.setattr(
        "application.image_generation.prompts.generate_sprite_prompts", generate
    )
    with pytest.raises(ValueError):
        _generate_sprite_prompts(SimpleNamespace(), "task", payload)
    generate.assert_not_called()


def test_prompt_request_for_missing_character_does_not_call_llm(monkeypatch):
    generate = Mock()
    monkeypatch.setattr(
        "application.image_generation.prompts.generate_sprite_prompts", generate
    )
    config = SimpleNamespace(get_character_by_name=lambda name: None)
    with pytest.raises(KeyError, match="character not found"):
        _generate_sprite_prompts(
            SimpleNamespace(config_manager=config), "task", {"characterName": "Rafal"}
        )
    generate.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "raw_prompts,expected",
    [
        (["Keep face, hair and outfit: wave"], "Keep face, hair and outfit: wave"),
        (["保持人物外观：右手挥手"], "保持人物外观：右手挥手"),
        (["Sprite 1: Keep identity: wave"], "Sprite 1: Keep identity: wave"),
        ("Sprite 1: Keep identity: wave", "Keep identity: wave"),
        ("立绘 1：保持人物外观：右手挥手", "保持人物外观：右手挥手"),
        ("立ち絵 1：Keep identity: wave", "Keep identity: wave"),
        ("Keep face, hair and outfit: wave", "Keep face, hair and outfit: wave"),
    ],
)
def test_bridge_validates_local_references_and_passes_order_to_application(
    tmp_path, monkeypatch, legacy, raw_prompts, expected
):
    references = [tmp_path / "first.png", tmp_path / "second.png"]
    for path in references:
        path.write_bytes(b"image")
    output = tmp_path / "generated.png"
    output.write_bytes(b"result")
    generate = Mock(return_value=[str(output)])
    updates = Mock()
    monkeypatch.setattr(
        "application.image_generation.sprites.generate_sprites", generate
    )
    monkeypatch.setattr(
        "frontend_bridge_core.tools._local_file_access_roots", lambda state: [tmp_path]
    )
    monkeypatch.setattr(
        "frontend_bridge_core.tools._sprite_output_dir", lambda *args: tmp_path
    )
    monkeypatch.setattr("frontend_bridge_core.tools._update_task", updates)
    payload = {
        "characterName": "Rafal",
        "prompts": raw_prompts,
        "provider": "configured",
    }
    if legacy:
        payload["referenceImage"] = str(references[0])
    else:
        payload["referenceImages"] = [str(path) for path in references]
    state = SimpleNamespace(config_manager=object())
    result = _generate_sprites(state, "task", payload)
    assert generate.call_args.kwargs["reference_images"] == (
        references[:1] if legacy else references
    )
    assert generate.call_args.kwargs["prompts"] == [expected]
    assert generate.call_args.kwargs["provider"] == "configured"
    assert result["files"] == [output.as_posix()]


@pytest.mark.parametrize("references", ["a.png", [], [None], [""], ["a.png"] * 11])
def test_bridge_rejects_malformed_reference_array(references):
    with pytest.raises(ValueError, match="referenceImages"):
        _generate_sprites(
            SimpleNamespace(),
            "task",
            {"characterName": "Rafal", "referenceImages": references},
        )


def test_bridge_rejects_reference_outside_allowed_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    image = tmp_path / "outside.png"
    image.write_bytes(b"reference")
    monkeypatch.setattr(
        "frontend_bridge_core.tools._local_file_access_roots", lambda state: [allowed]
    )
    with pytest.raises((ValueError, PermissionError)):
        _generate_sprites(
            SimpleNamespace(),
            "task",
            {"characterName": "Rafal", "referenceImages": [str(image)]},
        )


def test_generated_image_labels_are_returned_without_mutating_the_character(
    tmp_path, monkeypatch
):
    reference = tmp_path / "original.png"
    reference.write_bytes(b"reference")
    output = tmp_path / "generated.png"
    output.write_bytes(b"image")
    generate = Mock(return_value=[str(output)])
    label = Mock(return_value=(["smiling, waving"], []))
    updates = Mock()
    monkeypatch.setattr(
        "application.image_generation.sprites.generate_sprites", generate
    )
    monkeypatch.setattr(
        "application.image_generation.labels.label_generated_sprites", label
    )
    monkeypatch.setattr(
        "frontend_bridge_core.tools._local_file_access_roots", lambda state: [tmp_path]
    )
    monkeypatch.setattr(
        "frontend_bridge_core.tools._sprite_output_dir", lambda *args: tmp_path
    )
    monkeypatch.setattr("frontend_bridge_core.tools._update_task", updates)
    config = Mock()
    result = _generate_sprites(
        SimpleNamespace(config_manager=config),
        "task",
        {
            "characterName": "Rafal",
            "referenceImages": [str(reference)],
            "prompts": ["wave"],
            "autoLabel": True,
            "seed": 456,
        },
    )
    assert result["files"] == [output.as_posix()]
    assert result["labels"] == ["smiling, waving"] and result["labelErrors"] == []
    assert generate.call_args.kwargs["seed"] == 456
    assert label.call_args.args == (config, [output.as_posix()])
    config.save_characters_config.assert_not_called()
    assert updates.call_args.kwargs["result"] == result


@pytest.mark.parametrize(
    "field,value",
    [
        ("autoLabel", "false"),
        ("autoLabel", 1),
        ("seed", True),
        ("seed", -2),
        ("seed", 2**32),
        ("seed", 1.5),
    ],
)
def test_invalid_generation_options_do_not_start_inference(field, value):
    with pytest.raises(ValueError, match=field):
        _generate_sprites(
            SimpleNamespace(), "task", {"characterName": "Rafal", field: value}
        )

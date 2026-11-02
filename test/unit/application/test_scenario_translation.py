from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.localization.scenario_translation import translate_scenario_names
from frontend_bridge_core.characters import _translate_scenario_names


def test_translation_uses_application_llm_and_preserves_indices(monkeypatch):
    chat = Mock(return_value='```json\n{"translations": ["Sad-Face", "laugh"]}\n```')
    monkeypatch.setattr("application.localization.scenario_translation._llm_one_shot", chat)
    assert translate_scenario_names(object(), ["happy", "悲伤", "大笑"]) == {"1": "sad-face", "2": "laugh"}
    assert "悲伤" in chat.call_args.args[2]


def test_english_tags_do_not_call_llm(monkeypatch):
    chat = Mock()
    monkeypatch.setattr("application.localization.scenario_translation._llm_one_shot", chat)
    assert translate_scenario_names(object(), ["happy", "sad-face", ""]) == {}
    chat.assert_not_called()


@pytest.mark.parametrize("response", [
    "not JSON", '{"translations": []}', '{"translations": "sad"}',
    '{"translations": [null]}', '{"translations": ["two words"]}',
])
def test_invalid_translation_reports_failure(monkeypatch, response):
    monkeypatch.setattr("application.localization.scenario_translation._llm_one_shot", lambda *_: response)
    with pytest.raises(ValueError):
        translate_scenario_names(object(), ["悲伤"])


def test_translation_propagates_llm_failure(monkeypatch):
    monkeypatch.setattr("application.localization.scenario_translation._llm_one_shot", Mock(side_effect=ValueError("llm_incomplete")))
    with pytest.raises(ValueError, match="llm_incomplete"):
        translate_scenario_names(object(), ["悲伤"])


def test_bridge_delegates_translation_and_uses_requested_names(monkeypatch):
    config = SimpleNamespace(get_character_by_name=lambda _: SimpleNamespace(scenarios=[]))
    translate = Mock(return_value={"0": "sad"})
    monkeypatch.setattr("application.localization.scenario_translation.translate_scenario_names", translate)
    assert _translate_scenario_names(SimpleNamespace(config_manager=config), {"name": "Alice", "names": ["悲伤"]}) == {"translated": {"0": "sad"}}
    translate.assert_called_once_with(config, ["悲伤"])

import sys
from types import ModuleType, SimpleNamespace

import pytest

from frontend_bridge_core.templates import (
    MARK_SCENARIO,
    MARK_SYSTEM,
    _compose_runtime_template,
    _compose_stored_template,
    _generate_template_summary,
    _has_untranslated_template_keys,
    _history_id_from_scenario,
    _parse_stored_template,
    _scenario_from_template_like,
    _safe_session_int,
    _save_template_session_payload,
    _template_session_to_frontend,
)
from llm.template_generator import TemplateGenerator


def test_stored_template_round_trips_scenario_and_system_sections():
    raw = _compose_stored_template("  opening\r\nscene  ", " system\r\nrules ")

    assert raw == f"{MARK_SCENARIO}\n  opening\nscene\n{MARK_SYSTEM}\n system\nrules\n"
    assert _parse_stored_template(raw) == ("  opening\nscene", " system\nrules")


def test_parse_stored_template_handles_legacy_single_body_text():
    assert _parse_stored_template("legacy template") == ("legacy template", "")
    assert _parse_stored_template("  \n") == ("", "")


def test_history_id_uses_effective_scenario_and_selected_characters():
    scenario_id = _history_id_from_scenario("scenario", ["Alice", "Bob"])
    assert scenario_id == _history_id_from_scenario(" scenario ", ["Bob", "Alice", "Alice"])
    assert scenario_id != _history_id_from_scenario("scenario", ["Alice"])
    assert scenario_id != _history_id_from_scenario("another scenario", ["Alice", "Bob"])
    assert _history_id_from_scenario("") == _history_id_from_scenario(
        "你扮演一个RPG系统。",
    )


def test_runtime_template_places_json_reminder_after_user_scenario(monkeypatch):
    monkeypatch.setattr(
        "frontend_bridge_core.templates.json_format_reminder",
        lambda: "必须以规定的 JSON 格式回复。",
    )

    assert _compose_runtime_template("system rules", "user scenario") == (
        "system rules\nuser scenario\n必须以规定的 JSON 格式回复。\n"
    )


def test_runtime_template_places_json_reminder_after_default_scenario(monkeypatch):
    monkeypatch.setattr(
        "frontend_bridge_core.templates.json_format_reminder",
        lambda: "必须以规定的 JSON 格式回复。",
    )

    assert _compose_runtime_template("system rules", "") == (
        "system rules\n你扮演一个RPG系统。\n必须以规定的 JSON 格式回复。\n"
    )


def test_generate_template_summary_returns_canonical_resolved_characters(monkeypatch):
    character = SimpleNamespace(
        name="Alice",
        sprites=[],
        emotion_tags="",
        character_setting="",
    )
    config_manager = SimpleNamespace(
        get_character_by_name=lambda name: character if name.lower() == "alice" else None,
    )
    monkeypatch.setattr(
        "llm.template_generator.config_manager",
        config_manager,
    )
    monkeypatch.setattr(
        "llm.template_generator._T",
        lambda key, **kwargs: f"{key}:{kwargs}\n",
    )
    state = SimpleNamespace(
        config_manager=config_manager,
        template_generator=TemplateGenerator(output_contract_patches=[]),
    )

    summary = _generate_template_summary(
        state,
        {
            "backgroundName": "",
            "characters": ["Deleted", " alice "],
            "name": "restored",
            "scenario": "Restored scenario",
            "useTranslation": False,
        },
    )

    assert summary["resolvedCharacters"] == ["Alice"]
    assert "Alice" in summary["system"]
    assert "Deleted" not in summary["system"]


def test_generate_template_summary_rejects_all_stale_characters(monkeypatch):
    config_manager = SimpleNamespace(get_character_by_name=lambda _name: None)
    monkeypatch.setattr(
        "llm.template_generator.config_manager",
        config_manager,
    )
    monkeypatch.setattr(
        "llm.template_generator._T",
        lambda key, **kwargs: f"template_gen.{key}",
    )
    state = SimpleNamespace(
        config_manager=config_manager,
        template_generator=TemplateGenerator(output_contract_patches=[]),
    )

    with pytest.raises(ValueError, match="template_gen.err_no_characters"):
        _generate_template_summary(
            state,
            {
                "backgroundName": "",
                "characters": ["Deleted"],
                "name": "restored",
                "scenario": "Restored scenario",
                "useTranslation": False,
            },
        )


def test_save_template_session_persists_only_resolved_characters_and_their_default_sprite(monkeypatch):
    character = SimpleNamespace(
        name="Alice",
        sprites=[SimpleNamespace(path="sprites/alice.png")],
    )
    config_manager = SimpleNamespace(
        config=SimpleNamespace(characters=[character]),
        get_character_by_name=lambda name: character if name.lower() == "alice" else None,
    )
    saved: dict[str, object] = {}
    settings_package = ModuleType("ui.settings_ui")
    settings_package.__path__ = []
    services_package = ModuleType("ui.settings_ui.services")
    services_package.__path__ = []
    storage_module = ModuleType("ui.settings_ui.services.template_tab_session")
    storage_module.save_template_session = lambda _path, data: saved.update(data)
    storage_module.load_template_session = lambda _path: dict(saved)
    monkeypatch.setitem(sys.modules, "ui.settings_ui", settings_package)
    monkeypatch.setitem(sys.modules, "ui.settings_ui.services", services_package)
    monkeypatch.setitem(sys.modules, "ui.settings_ui.services.template_tab_session", storage_module)
    state = SimpleNamespace(
        config_manager=config_manager,
        template_dir_path="unused",
    )

    restored = _save_template_session_payload(
        state,
        {
            "initSpritePath": "",
            "scenario": "Restored scenario",
            "selectedCharacters": ["Deleted", " alice "],
            "system": "Generated system",
        },
    )

    assert saved["selected_characters"] == ["Alice"]
    assert saved["init_sprite_path"] == "sprites/alice.png"
    assert restored["selectedCharacters"] == ["Alice"]
    assert restored["initSpritePath"] == "sprites/alice.png"


def test_scenario_from_template_like_falls_back_only_for_none():
    assert _scenario_from_template_like({"scenario": None, "content": "legacy"}) == "legacy"
    assert _scenario_from_template_like({"scenario": "", "content": "legacy"}) == ""
    assert _scenario_from_template_like({"content": "legacy"}) == "legacy"


def test_template_session_to_frontend_normalizes_types_and_defaults():
    assert _template_session_to_frontend(None) is None
    assert _template_session_to_frontend(
        {
            "background": "校门",
            "filename_stub": "demo",
            "history_file": "/tmp/history.json",
            "init_sprite_path": "/tmp/sprite.png",
            "max_dialog_items": "8",
            "max_speech_chars": "bad",
            "room_id": 123,
            "scenario_text": "场景",
            "selected_characters": ["Alice", "", 42],
            "system_template_text": "系统",
            "template_file_dropdown": "demo.txt",
            "workflow_path": "test/e2e/live_bridge_runtime.yaml",
            "use_cg_yes": True,
            "use_choice_yes": False,
            "use_cot_yes": True,
            "use_effect_yes": False,
            "use_narration_yes": False,
            "use_stat_yes": False,
            "use_tr_yes": False,
            "voice_lang": "ja",
        }
    ) == {
        "background": "校门",
        "filenameStub": "demo",
        "historyPath": "/tmp/history.json",
        "initSpritePath": "/tmp/sprite.png",
        "maxDialogItems": 8,
        "maxSpeechChars": 0,
        "roomId": "123",
        "scenario": "场景",
        "selectedCharacters": ["Alice", "42"],
        "system": "系统",
        "templateFileDropdown": "demo.txt",
        "workflowPath": "test/e2e/live_bridge_runtime.yaml",
        "useCg": True,
        "useChoice": False,
        "useCot": True,
        "useEffect": False,
        "useNarration": False,
        "useStat": False,
        "useTranslation": False,
        "voiceLanguage": "ja",
    }


def test_safe_session_int_and_untranslated_key_detection():
    assert _safe_session_int("5") == 5
    assert _safe_session_int("-5") == 0
    assert _safe_session_int("bad", default=9) == 9
    assert _has_untranslated_template_keys("template_gen.foo") is True
    assert _has_untranslated_template_keys("normal", None) is False

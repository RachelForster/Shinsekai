from frontend_bridge_core.templates import (
    MARK_SCENARIO,
    MARK_SYSTEM,
    _compose_stored_template,
    _has_untranslated_template_keys,
    _history_id_from_scenario,
    _parse_stored_template,
    _safe_session_int,
    _template_session_to_frontend,
)


def test_stored_template_round_trips_scenario_and_system_sections():
    raw = _compose_stored_template("  opening\r\nscene  ", " system\r\nrules ")

    assert raw == f"{MARK_SCENARIO}\n  opening\nscene\n{MARK_SYSTEM}\n system\nrules\n"
    assert _parse_stored_template(raw) == ("  opening\nscene", " system\nrules")


def test_parse_stored_template_handles_legacy_single_body_text():
    assert _parse_stored_template("legacy template") == ("legacy template", "")
    assert _parse_stored_template("  \n") == ("", "")


def test_history_id_uses_effective_scenario_and_selected_characters():
    scenario_id = _history_id_from_scenario("scenario", "system", ["Alice", "Bob"])
    assert scenario_id == _history_id_from_scenario(" scenario ", "ignored", ["Bob", "Alice", "Alice"])
    assert scenario_id != _history_id_from_scenario("scenario", "system", ["Alice"])
    assert scenario_id != _history_id_from_scenario("another scenario", "system", ["Alice", "Bob"])
    assert _history_id_from_scenario("", "system") == _history_id_from_scenario(
        "你扮演一个RPG系统。",
        "ignored",
    )


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

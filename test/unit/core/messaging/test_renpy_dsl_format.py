from __future__ import annotations

import pytest

from application.chat.dialog_formats import list_dialog_formats
from core.chat_history.text import parse_assistant_dialog_content
from core.messaging.formats import (
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
    detect_dialog_format,
    is_builtin_dialog_format,
    parse_dialog_content,
    resolve_dialog_format,
)
from core.messaging.formats.registry import _reset_for_tests
from core.messaging.formats.renpy import (
    RenpyDslDialogFormat,
    RenpyDslPlugin,
    RenpyDslStreamParser,
    get_default_renpy_prompt_provider,
    set_default_renpy_prompt_provider,
)
from i18n import bind_language
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogFormatContribution,
    DialogFormatPromptContext,
    DialogOutfitHintContext,
    DialogPlayerHintContext,
    RENPY_DIALOG_FORMAT_ID,
    XML_DIALOG_FORMAT_ID,
)
from sdk.lang import SUPPORTED_LANGS
from sdk.manager import PluginManager
from sdk.messages import LLMDialogMessage


@pytest.fixture(autouse=True)
def _restore_dialog_format_registry():
    _reset_for_tests()
    configure_builtin_dialog_formats()
    yield
    _reset_for_tests()
    configure_builtin_dialog_formats()


def test_renpy_parser_streams_char_by_char_across_all_directives() -> None:
    payload = '''<think>
internal reasoning split across lines
</think>
```renpy
# Scene setup
cot: <摘要>Greeting</摘要><动机>Check in</动机><剧情走向>Talk</剧情走向>
scene bg_01 [effect="rain"] with dip-black
play music bgm_02
show "Dr. Smith" [sprite="02", motion="quiver"]
"Dr. Smith" [effect="spark", outfit="casual"] "Hello \\"friend\\"" | tr "你好，\\"朋友\\""
narr [effect="wind"] "The wind rises."
"Bare narration works too."
stat "heart|HP|72|100"
cg [sprite="cg_01"] "highres, masterpiece, 8k, rain scene"
menu:
  "Ask about rain":
  "Stay silent"
hide "Dr. Smith"
```'''
    parser = RenpyDslStreamParser()
    emitted: list[LLMDialogMessage] = []
    for ch in payload:
        emitted.extend(parser.feed(ch))
    emitted.extend(parser.flush())

    assert not parser.has_errors, parser.last_error
    assert len(emitted) == 10

    assert emitted[0].name == "COT"
    assert "<摘要>Greeting</摘要>" in (emitted[0].text or "")

    assert emitted[1].name == "SCENE"
    assert emitted[1].asset_id == "bg_01"
    assert emitted[1].effect == "rain"
    assert emitted[1].transition == "fade_black"

    assert emitted[2].name == "bgm"
    assert emitted[2].asset_id == "bgm_02"

    assert emitted[3].name == "Dr. Smith"
    assert emitted[3].asset_id == "02"
    assert emitted[3].motion == "tremble"
    assert emitted[3].effect == "spark"
    assert emitted[3].outfit == "casual"
    assert emitted[3].text == 'Hello "friend"'
    assert emitted[3].translate == '你好，"朋友"'

    assert emitted[4].name == "NARR"
    assert emitted[4].text == "The wind rises."
    assert emitted[4].effect == "wind"

    assert emitted[5].name == "NARR"
    assert emitted[5].text == "Bare narration works too."

    assert emitted[6].name == "STAT"
    assert emitted[6].text == "heart|HP|72|100"

    assert emitted[7].name == "CG"
    assert emitted[7].asset_id == "cg_01"
    assert "highres" in (emitted[7].text or "")

    assert emitted[8].name == "CHOICE"
    assert emitted[8].text == "Ask about rain / Stay silent"

    assert emitted[9].name == "Dr. Smith"
    assert emitted[9].effect == "LEAVE"
    assert emitted[9].text == ""


def test_renpy_round_trip_and_cross_format_serialization() -> None:
    items = [
        LLMDialogMessage(character_name="COT", sprite="-1", speech="<摘要>S</摘要><动机>M</动机><剧情走向>N</剧情走向>"),
        LLMDialogMessage(character_name="SCENE", sprite="01", transition="fade_black", effect="ambient:rain"),
        LLMDialogMessage(character_name="bgm", sprite="02"),
        LLMDialogMessage(
            character_name="Alice",
            sprite="03",
            outfit="summer",
            motion="nod",
            effect="spark",
            speech="Watch out!",
            translate="小心！",
        ),
        LLMDialogMessage(character_name="NARR", sprite="-1", speech="Rain begins."),
        LLMDialogMessage(character_name="STAT", sprite="-1", speech="heart|HP|90|100"),
        LLMDialogMessage(character_name="CG", sprite="-1", speech="highres, sunset"),
        LLMDialogMessage(character_name="CHOICE", sprite="-1", speech="Help / Run"),
        LLMDialogMessage(character_name="Alice", sprite="-1", speech="", effect="LEAVE"),
    ]
    renpy_fmt = resolve_dialog_format(RENPY_DIALOG_FORMAT_ID)
    serialized = renpy_fmt.serialize(items)
    assert isinstance(serialized, str) and "scene 01" in serialized
    reparsed = renpy_fmt.parse_complete(serialized)
    assert [(m.name, m.text, m.asset_id, m.motion, m.transition, m.outfit) for m in reparsed] == [
        (m.name, m.text, str(m.asset_id), m.motion, m.transition, m.outfit) for m in items
    ]
    assert reparsed[3].translate == "小心！"
    assert reparsed[3].effect == "spark"
    assert reparsed[-1].effect == "LEAVE"

    # Cross-format conversion renpy -> xml -> json -> renpy
    xml_fmt = resolve_dialog_format(XML_DIALOG_FORMAT_ID)
    json_fmt = resolve_dialog_format(DEFAULT_DIALOG_FORMAT_ID)
    xml_text = xml_fmt.serialize(reparsed)
    assert xml_text and "<say " in xml_text
    from_xml = xml_fmt.parse_complete(xml_text)
    json_text = json_fmt.serialize(from_xml)
    assert json_text and '"dialog"' in json_text
    from_json = json_fmt.parse_complete(json_text)
    back_to_renpy = renpy_fmt.serialize(from_json)
    assert back_to_renpy and "menu:" in back_to_renpy

    # History auto-detection distinguishes renpy from xml and json (including fenced JSON)
    assert detect_dialog_format(serialized) is not None
    assert detect_dialog_format(serialized).format_id == RENPY_DIALOG_FORMAT_ID  # type: ignore[union-attr]
    assert detect_dialog_format(xml_text).format_id == XML_DIALOG_FORMAT_ID  # type: ignore[union-attr]
    assert detect_dialog_format(f"```\n{json_text}\n```").format_id == DEFAULT_DIALOG_FORMAT_ID  # type: ignore[union-attr]
    history = parse_assistant_dialog_content('Alice [sprite="01", motion="nod"] "Hi!"')
    assert history and history[0]["character_name"] == "Alice" and history[0]["motion"] == "nod"


def test_renpy_validate_and_error_recovery() -> None:
    fmt = RenpyDslDialogFormat()
    requires_alice = lambda speaker: speaker == "Alice"

    assert fmt.validate('Alice [sprite="01"] "Hello"', speaker_requires_media=requires_alice) is True
    assert fmt.validate('Alice [sprite="-1"] "Keep pose"', speaker_requires_media=requires_alice) is True
    # Missing sprite on bound speaker is rejected, while unbound bystander passes.
    assert fmt.validate('Alice "Forgot sprite"', speaker_requires_media=requires_alice) is False
    assert fmt.validate('Bystander "Passing by"', speaker_requires_media=requires_alice) is True

    # Semantic mode enforcement
    assert fmt.validate('scene vibe="sunny park" with fade\nAlice [vibe="smiling"] "Hi!"', media_selection_mode="semantic", speaker_requires_media=requires_alice) is True
    assert fmt.validate('scene 01\nAlice [vibe="smiling"] "Hi!"', media_selection_mode="semantic", speaker_requires_media=requires_alice) is False
    assert fmt.validate('scene vibe="sunny park"\nAlice [sprite="01"] "Hi!"', media_selection_mode="semantic", speaker_requires_media=requires_alice) is False

    # Plain prose, malformed directives, and unclosed <think> fail validation
    assert fmt.validate("Just some plain text without DSL") is False
    assert fmt.validate("hide\nscene") is False
    assert fmt.validate("<think>unclosed reasoning") is False

    # Truncated final line at EOF recovers cleanly while malformed line increments parse_failures
    parsed = parse_dialog_content('Alice [sprite="01"] "Truncated line', format_id=RENPY_DIALOG_FORMAT_ID)
    assert len(parsed) == 1 and parsed[0].text == "Truncated line"


def test_renpy_builtin_plugin_registration_lifecycle(caplog) -> None:
    mgr = PluginManager()
    mgr.register_plugin_class(RenpyDslPlugin)
    mgr.instantiate_all()
    mgr.load_own_config_all()
    contributions = mgr.collect_dialog_formats()
    assert len(contributions) == 1
    assert contributions[0].format_id == RENPY_DIALOG_FORMAT_ID
    assert contributions[0].plugin_id == "shinsekai.builtin.renpy_dsl_format"

    with caplog.at_level("ERROR"):
        configure_registered_dialog_formats(contributions)
    assert not caplog.records
    assert is_builtin_dialog_format(RENPY_DIALOG_FORMAT_ID) is True
    by_id = {row["id"]: row for row in list_dialog_formats()}
    assert by_id[RENPY_DIALOG_FORMAT_ID]["builtin"] is True

    # External plugins still cannot shadow builtin format ids.
    with caplog.at_level("ERROR"):
        configure_registered_dialog_formats(
            [
                DialogFormatContribution(
                    format_id=RENPY_DIALOG_FORMAT_ID,
                    factory=RenpyDslDialogFormat,
                    label="Shadowed",
                    plugin_id="third_party.plugin",
                )
            ]
        )
    assert any("conflicts with builtin" in rec.message for rec in caplog.records)


def test_renpy_parser_menu_show_edge_cases_and_error_branches() -> None:
    plugin = RenpyDslPlugin()
    assert plugin.plugin_name and plugin.plugin_version and plugin.plugin_description and plugin.plugin_author

    # Unquoted hide, inline menu/choice, show <id> at <motion>, cot quoted, bgm shorthand, menu followed by say
    script = """cot: "Plan step"
scene [vibe="dusk street"] with fade
bgm 03
show Alice 04 at nod
Alice [leave] "Leaving now"
menu: "Opt A" | "Opt B"
menu:
  # skip comment inside menu
  - First choice
  * Second choice
Alice [sprite="01"] "After menu"
hide Alice
narr [sprite="01", tr="旁白译文"] "Line\\\\with\\ttabs"
"""
    parser = RenpyDslStreamParser()
    assert parser.buffer == ""
    assert parser.unparsed_remainder == ""
    out = list(parser.feed(script))
    out.extend(parser.flush())
    assert not parser.has_errors, parser.last_error
    assert len(out) == 9
    assert out[0].name == "COT" and out[0].text == "Plan step"
    assert out[2].name == "bgm" and out[2].asset_id == "03"
    assert out[3].asset_id == "04" and out[3].motion == "nod" and out[3].effect == "LEAVE"
    assert out[4].name == "CHOICE" and out[4].text == "Opt A / Opt B"
    assert out[5].name == "CHOICE" and out[5].text == "First choice / Second choice"
    assert out[6].name == "Alice" and out[6].text == "After menu"
    assert out[7].name == "Alice" and out[7].effect == "LEAVE"
    assert out[8].name == "NARR" and out[8].translate == "旁白译文" and "\t" in (out[8].text or "")

    # Bare quoted narration truncated at EOF & escaped bracket attributes
    trunc_parser = RenpyDslStreamParser()
    trunc_out = list(trunc_parser.feed('"Halfway narration')) + trunc_parser.flush()
    assert len(trunc_out) == 1 and trunc_out[0].name == "NARR"
    leave_parser = RenpyDslStreamParser()
    leave_out = list(leave_parser.feed('Alice [LEAVE, \'02\'] "Bye"')) + leave_parser.flush()
    assert len(leave_out) == 1 and leave_out[0].effect == "LEAVE"

    # Malformed directives & unclosed tokens record localized structured RenpyParseError codes
    bad_cases: list[tuple[str, str]] = [
        ("cot: ", "empty_cot"),
        ('scene [sprite="unclosed', "unclosed_brackets"),
        ('scene "unclosed', "unclosed_quote"),
        ("play music", "missing_bgm_media"),
        ("scene", "missing_scene_media"),
        ('play music [sprite="unclosed', "unclosed_brackets"),
        ('play music "unclosed', "unclosed_quote"),
        ('cg [sprite="unclosed', "unclosed_brackets"),
        ('cg "unclosed" trailing', "unexpected_trailing"),
        ('cg "unclosed\n', "unclosed_quote"),
        ("cg", "missing_cg_content"),
        ("stat:", "empty_stat"),
        ('stat "unclosed', "unclosed_quote"),
        ('stat "ok" extra', "unexpected_trailing"),
        ("choice:   ", "missing_choice_options"),
        ("menu:", "missing_choice_options"),
        ("hide", "missing_character_name"),
        ('hide ""', "invalid_character_name"),
        ("show", "missing_character_name"),
        ('show ""', "invalid_character_name"),
        ('show "Bad" [unclosed', "unclosed_brackets"),
        ('narr [sprite="unclosed', "unclosed_brackets"),
        ("narr missing_quotes", "missing_quoted_text"),
        ('narr "unclosed\n', "unclosed_speech"),
        ('Alice "hi" | bad', "unexpected_trailing_dialogue"),
        ('Alice "hi" | tr', "empty_translate"),
        ('Alice "hi" | tr "', "unclosed_translate"),
        ('Alice "hi" | tr "ok" extra', "unexpected_trailing_translate"),
        ('"Unclosed bare narration\n', "unclosed_narration"),
        ('"" "empty speaker"', "unrecognized_line"),
        ('Alice [unclosed "hi"', "unclosed_brackets"),
        ("Alice missing_quote", "unrecognized_line"),
        ('Alice "unclosed\n', "unclosed_speech"),
    ]
    for bad, expected_code in bad_cases:
        err_parser = RenpyDslStreamParser(locale="en")
        list(err_parser.feed(bad))
        err_parser.flush()
        assert err_parser.has_errors, f"Expected error for {bad!r}"
        assert err_parser.last_error_code == expected_code
        localized_messages = {err_parser.format_last_error(locale=loc) for loc in SUPPORTED_LANGS}
        assert all(localized_messages) and len(localized_messages) == 3

    with bind_language("ja"):
        ja_parser = RenpyDslStreamParser()
        list(ja_parser.feed("cot: \n"))
        ja_parser.flush()
        assert ja_parser.last_error_code == "empty_cot"
        assert "空" in ja_parser.last_error and ja_parser.format_last_error() == ja_parser.last_error


def test_renpy_pure_core_provider_detachment_and_prompt_hooks() -> None:
    fmt = RenpyDslDialogFormat()
    assert fmt.can_parse("") is False
    assert fmt.can_parse("Just plain text") is False
    assert fmt.can_parse('<say char="Alice">Hi</say>') is False
    assert fmt.can_parse('```\n{"dialog": []}\n```') is False

    # Pure core format works for parse/validate/serialize and returns None from prompt hooks without a provider.
    previous_provider = get_default_renpy_prompt_provider()
    try:
        set_default_renpy_prompt_provider(None)
        pure_fmt = RenpyDslDialogFormat()
        assert pure_fmt.parse_complete('Alice [sprite="01"] "Ok"')[0].text == "Ok"
        assert pure_fmt.validate('Alice [sprite="01"] "Ok"') is True
        assert pure_fmt.render_schema_hint(media_field="sprite", translate_required=False, locale="en") is None
        assert pure_fmt.render_requirements(DialogFormatPromptContext(locale="en")) is None
        assert pure_fmt.render_outfit_hint(DialogOutfitHintContext(locale="en")) is None
        assert pure_fmt.render_player_hint(DialogPlayerHintContext(locale="en", name="Hero")) is None
        assert pure_fmt.render_format_reminder(locale="en") is None
        assert pure_fmt.render_repair_prompt(media_field="sprite", retry=False, locale="en") is None
    finally:
        set_default_renpy_prompt_provider(previous_provider)

    # Unknown locale safely falls back to zh_CN via template provider hooks
    from ai.llm.template.dialog.renpy_prompts import ensure_renpy_prompt_provider_registered

    ensure_renpy_prompt_provider_registered()
    reminder = fmt.render_format_reminder(locale="fr_FR")
    assert reminder is not None and "Ren'Py" in reminder

    locked_hint = fmt.render_outfit_hint(
        DialogOutfitHintContext(locale="en", auto_switch_enabled=False, media_selection_mode="semantic")
    )
    assert locked_hint is not None and locked_hint.example_line == ""

    semantic_hint = fmt.render_outfit_hint(
        DialogOutfitHintContext(
            locale="ja",
            media_selection_mode="semantic",
            auto_switch_enabled=True,
            example_character="Dr [1]",
            example_target_group="summer",
            example_vibe="smile",
            example_speech="Hi",
        )
    )
    assert semantic_hint is not None and 'vibe="smile"' in semantic_hint.example_line and '"Dr [1]"' in semantic_hint.example_line

    player_disabled = fmt.render_player_hint(
        DialogPlayerHintContext(
            locale="zh_CN",
            name="Hero",
            setting="Protag",
            uses_vibe=True,
            allow_player_dialogue=False,
            read_player_speech=False,
            portrait_field="vibe",
            portrait_value="calm",
        )
    )
    assert player_disabled is not None and "Hero" in player_disabled and "不要为主控输出朗读行" in player_disabled


def test_renpy_review_regressions() -> None:
    fmt = RenpyDslDialogFormat()

    # #1: Bracketed scene transition forms parse cleanly
    bracketed = fmt.parse_complete(
        'scene 01 [with fade]\nscene 02 [effect="rain", with dip-black]\nAlice [sprite="01"] "Ok"'
    )
    assert len(bracketed) == 3
    assert bracketed[0].transition == "fade" and bracketed[0].asset_id == "01"
    assert bracketed[1].transition == "fade_black" and bracketed[1].effect == "rain"

    # #2: Unterminated | tr "..." at an ordinary newline fails parse & validate, while EOF truncation salvages.
    broken_tr = 'Alice [sprite="01"] "Hi" | tr "unclosed\nAlice [sprite="02"] "Next"'
    tr_parser = RenpyDslStreamParser()
    list(tr_parser.feed(broken_tr))
    tr_parser.flush()
    assert tr_parser.has_errors
    assert fmt.validate(broken_tr) is False
    eof_tr = fmt.parse_complete('Alice [sprite="01"] "Hi" | tr "你好')
    assert len(eof_tr) == 1 and eof_tr[0].translate == "你好"

    # #4: Indexed mode rejects vibe-only or -1 SCENE/bgm directives while allowing explicit IDs.
    assert fmt.validate('scene vibe="sunset"\nAlice [sprite="01"] "Hi"', media_selection_mode="indexed") is False
    assert fmt.validate('play music vibe="calm"\nAlice [sprite="01"] "Hi"', media_selection_mode="indexed") is False
    assert fmt.validate('scene -1\nAlice [sprite="01"] "Hi"', media_selection_mode="indexed") is False
    assert fmt.validate('scene 01\nplay music 02\nAlice [sprite="01"] "Hi"', media_selection_mode="indexed") is True

    # #5: BGM preserves vibe alongside asset_id across serialize -> parse_complete round-trips.
    bgm_msg = LLMDialogMessage(character_name="bgm", sprite="02", vibe="tense", effect="loop:rain")
    serialized_bgm = fmt.serialize([bgm_msg])
    assert serialized_bgm == 'play music 02 [vibe="tense", effect="loop:rain"]'
    reparsed_bgm = fmt.parse_complete(serialized_bgm)
    assert len(reparsed_bgm) == 1
    assert reparsed_bgm[0].asset_id == "02"
    assert reparsed_bgm[0].vibe == "tense"
    assert reparsed_bgm[0].effect == "loop:rain"

    # #6: Reserved DSL keyword speakers are quoted on serialization and disambiguated when unquoted with attrs+speech.
    reserved_msgs = [
        LLMDialogMessage(character_name="show", sprite="01", speech="Stage left."),
        LLMDialogMessage(character_name="play", sprite="02", speech="Cue audio."),
        LLMDialogMessage(character_name="menu", sprite="03", speech="Today's menu."),
    ]
    serialized_reserved = fmt.serialize(reserved_msgs)
    assert serialized_reserved is not None and serialized_reserved.startswith('"show" [sprite="01"]')
    reparsed_reserved = fmt.parse_complete(serialized_reserved)
    assert [(m.name, str(m.asset_id), m.text) for m in reparsed_reserved] == [
        ("show", "01", "Stage left."),
        ("play", "02", "Cue audio."),
        ("menu", "03", "Today's menu."),
    ]
    # Unquoted `show [sprite="01"] "Hi"` and `hide [sprite="02"] "Bye"` parse as dialogue while `show Alice [sprite="02"]` stages.
    mixed = fmt.parse_complete(
        'show [sprite="01"] "Hi"\nhide [sprite="02"] "Peek"\nshow Alice [sprite="02"]\nAlice "Updated"'
    )
    assert len(mixed) == 3
    assert mixed[0].name == "show" and mixed[0].asset_id == "01" and mixed[0].text == "Hi"
    assert mixed[1].name == "hide" and mixed[1].asset_id == "02" and mixed[1].text == "Peek"
    assert mixed[2].name == "Alice" and mixed[2].asset_id == "02" and mixed[2].text == "Updated"

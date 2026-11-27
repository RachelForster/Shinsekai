from __future__ import annotations

from collections.abc import Sequence

import pytest

from ai.llm.formats import (
    JsonDialogFormat,
    XmlTagsDialogFormat,
    XmlTagsStreamParser,
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
    detect_dialog_format,
    get_dialog_format,
    parse_dialog_content,
    register_dialog_format,
    registered_dialog_formats,
    resolve_dialog_format,
)
from core.chat_history.text import parse_assistant_dialog_content
from core.messaging.dialog_output import has_valid_dialog_output
from core.messaging.formats.registry import _reset_for_tests
from core.messaging.stage_effects import (
    character_motion_duration_ms,
    normalize_character_motion,
    normalize_scene_transition,
    scene_transition_duration_ms,
)
from sdk.adapters.dialog_format import DialogFormatContribution, DialogOutputFormat
from sdk.messages import LLMDialogMessage


@pytest.fixture(autouse=True)
def _restore_dialog_format_registry():
    _reset_for_tests()
    configure_builtin_dialog_formats()
    yield
    _reset_for_tests()
    configure_builtin_dialog_formats()


def test_stage_effect_normalizers_and_durations() -> None:
    assert normalize_scene_transition("dip-black") == "fade_black"
    assert normalize_scene_transition("CrossFade") == "fade"
    assert normalize_scene_transition("instant") == "cut"
    assert normalize_scene_transition("unknown-transition") == ""
    assert scene_transition_duration_ms("fade_black") == 680
    assert scene_transition_duration_ms("cut") == 0

    assert normalize_character_motion("quiver") == "tremble"
    assert normalize_character_motion("flinch") == "shake"
    assert normalize_character_motion("lean-in") == "lean_in"
    assert normalize_character_motion("unknown-motion") == ""
    assert character_motion_duration_ms("shake") == 460


def test_xml_parser_streams_one_char_at_a_time_across_all_tags() -> None:
    payload = """<think>internal reasoning that must be stripped</think>
```xml
<dialog>
  <cot>
    <摘要>Testing scene start</摘要>
    <动机>Greet player</动机>
    <剧情走向>Next line</剧情走向>
  </cot>
  <scene sprite="bg_01" transition="dip-black" effect="rain" />
  <bgm sprite="bgm_02" />
  <say char="Alice" sprite="happy" motion="quiver" effect="spark" outfit="casual">
    Hey a < b and <_<!
    <tr>嘿，a < b 而且 <_<!</tr>
  </say>
  <narr>The rain starts.</narr>
  <stat>HP=100</stat>
  <choice>
    <option>Ask about the rain</option>
    <option>Say nothing</option>
  </choice>
  <cg sprite="cg_01" />
  <leave char="Alice" />
</dialog>
```"""
    parser = XmlTagsStreamParser()
    emitted: list[LLMDialogMessage] = []
    for ch in payload:
        emitted.extend(parser.feed(ch))
    emitted.extend(parser.flush())

    assert not parser.has_errors
    assert len(emitted) == 9

    assert emitted[0].name == "COT"
    assert "<摘要>Testing scene start</摘要>" in emitted[0].text

    assert emitted[1].name == "SCENE"
    assert emitted[1].asset_id == "bg_01"
    assert emitted[1].transition == "fade_black"
    assert emitted[1].effect == "rain"

    assert emitted[2].name == "bgm"
    assert emitted[2].asset_id == "bgm_02"

    assert emitted[3].name == "Alice"
    assert emitted[3].asset_id == "happy"
    assert emitted[3].motion == "tremble"
    assert emitted[3].effect == "spark"
    assert emitted[3].outfit == "casual"
    assert "a < b" in emitted[3].text and "<_<" in emitted[3].text
    assert emitted[3].translate == "嘿，a < b 而且 <_<!"

    assert emitted[4].name == "NARR"
    assert emitted[4].text == "The rain starts."

    assert emitted[5].name == "STAT"
    assert emitted[5].text == "HP=100"

    assert emitted[6].name == "CHOICE"
    assert "Ask about the rain" in emitted[6].text and "Say nothing" in emitted[6].text

    assert emitted[7].name == "CG"
    assert emitted[7].asset_id == "cg_01"

    assert emitted[8].name == "Alice"
    assert emitted[8].effect == "LEAVE"
    assert str(emitted[8].asset_id) == "-1"


def test_xml_parser_flush_handles_unclosed_say_and_validation() -> None:
    parser = XmlTagsStreamParser()
    assert list(parser.feed('<say char="Alice" sprite="01">Hello')) == []
    flushed = parser.flush()
    assert len(flushed) == 1
    assert flushed[0].name == "Alice"
    assert flushed[0].text == "Hello"

    assert has_valid_dialog_output(
        '<say char="Alice" sprite="01">Hello</say>',
        format_id="xml_v1",
    )
    assert has_valid_dialog_output(
        '<scene vibe="quiet dusk" transition="fade" /><say char="Alice" vibe="smiling">Hi</say>',
        media_selection_mode="semantic",
        format_id="xml_v1",
    )
    assert not has_valid_dialog_output(
        '<scene transition="fade" />',
        media_selection_mode="semantic",
        format_id="xml_v1",
    )


class _DummyScriptFormat(DialogOutputFormat):
    format_id = "script_v1"
    label = "Dummy Script"

    def create_stream_parser(self) -> XmlTagsStreamParser:
        return XmlTagsStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        items: list[LLMDialogMessage] = []
        for line in raw.splitlines():
            if line.startswith("SCRIPT:"):
                speaker, speech = line[len("SCRIPT:") :].split("|", 1)
                items.append(LLMDialogMessage(character_name=speaker, speech=speech))
        return items

    def validate(self, raw: str) -> bool:
        return "SCRIPT:" in raw

    def serialize(self, items: Sequence[LLMDialogMessage]) -> str | None:
        return "\n".join(f"SCRIPT:{item.name}|{item.text}" for item in items)


def test_pluggable_format_registry_and_history_autodetection() -> None:
    configure_registered_dialog_formats(
        [
            DialogFormatContribution(
                format_id="script_v1",
                factory=_DummyScriptFormat,
                label="Dummy Script",
                plugin_id="dummy-plugin",
            )
        ]
    )
    ids = [fmt.format_id for fmt in registered_dialog_formats()]
    assert ids[:4] == ["xml_v1", "renpy_v1", "json_v1", "script_v1"]

    fmt = resolve_dialog_format("script_v1")
    assert fmt.format_id == "script_v1"

    detected = detect_dialog_format("SCRIPT:Alice|Hello world")
    assert detected is not None and detected.format_id == "script_v1"
    parsed = parse_dialog_content("SCRIPT:Alice|Hello world")
    assert len(parsed) == 1 and parsed[0].name == "Alice" and parsed[0].text == "Hello world"

    xml_history = parse_assistant_dialog_content(
        '<say char="Alice" sprite="01" motion="nod">Hi</say>'
    )
    assert xml_history and xml_history[0]["character_name"] == "Alice"
    assert xml_history[0]["motion"] == "nod"

    json_history = parse_assistant_dialog_content(
        '{"dialog":[{"character_name":"Alice","sprite":"01","speech":"Hi"}]}'
    )
    assert json_history and json_history[0]["character_name"] == "Alice"

    assert _DummyScriptFormat().render_schema_hint(media_field="sprite", translate_required=False, locale="en") is None
    assert _DummyScriptFormat().render_format_reminder(locale="en") is None
    assert _DummyScriptFormat().render_repair_prompt(media_field="sprite", retry=False, locale="en") is None


def test_xml_format_serialize_round_trip_and_negative_validation() -> None:
    fmt = XmlTagsDialogFormat()
    items = [
        LLMDialogMessage(character_name="COT", sprite="-1", speech="plan"),
        LLMDialogMessage(character_name="SCENE", sprite="bg01", transition="fade_black", vibe="dusk"),
        LLMDialogMessage(character_name="SCENE", sprite="bg02", speech="Hall"),
        LLMDialogMessage(character_name="bgm", sprite="t01", effect="loop:wind"),
        LLMDialogMessage(character_name="bgm", sprite="t02", speech="Theme"),
        LLMDialogMessage(character_name="CG", sprite="cg01", vibe="sunset", speech="CG desc"),
        LLMDialogMessage(character_name="NARR", sprite="-1", speech="Rain falls.", translate="雨落下来。", motion="nod"),
        LLMDialogMessage(character_name="STAT", sprite="-1", speech="HP=90"),
        LLMDialogMessage(character_name="CHOICE", sprite="-1", speech="Go / Stay"),
        LLMDialogMessage(
            character_name="Alice",
            sprite="01",
            vibe="happy",
            outfit="school",
            motion="shake",
            effect="spark",
            speech="Hello!",
            translate="你好！",
        ),
        LLMDialogMessage(character_name="Alice", sprite="-1", speech="", effect="LEAVE"),
    ]
    serialized = fmt.serialize(items)
    assert serialized is not None
    reparsed = fmt.parse_complete(serialized)
    assert len(reparsed) == len(items)
    assert reparsed[1].transition == "fade_black"
    assert reparsed[6].translate == "雨落下来。"
    assert reparsed[6].motion == ""
    assert reparsed[9].outfit == "school" and reparsed[9].motion == "shake"
    assert reparsed[10].effect == "LEAVE"

    tricky_speech = 'Wait </say><say char="Evil">hacked</say> & a < b'
    tricky_cot = "step 1 </cot> step 2"
    escaped_xml = fmt.serialize(
        [
            LLMDialogMessage(character_name="COT", sprite="-1", speech=tricky_cot),
            LLMDialogMessage(character_name="Alice", sprite="01", speech=tricky_speech),
        ]
    )
    assert escaped_xml is not None
    assert escaped_xml.count("<say") == 1
    assert 'char="Evil"' not in escaped_xml or "&lt;/say&gt;" in escaped_xml
    reparsed_escaped = fmt.parse_complete(escaped_xml)
    assert len(reparsed_escaped) == 2
    assert reparsed_escaped[0].name == "COT"
    assert reparsed_escaped[0].text == tricky_cot
    assert reparsed_escaped[1].name == "Alice"
    assert reparsed_escaped[1].text == tricky_speech

    assert not fmt.validate("")
    assert not fmt.validate('<say char="Alice" sprite="01">hi</say><say char="Bob"')
    assert not fmt.validate("<say>missing char</say>")
    assert not fmt.can_parse("plain text without tags")
    assert not fmt.can_parse('{"dialog":[{"character_name":"Alice","sprite":"01","speech":"<say>hi</say>"}]}')


def test_json_format_parse_serialize_and_validation() -> None:
    fmt = JsonDialogFormat()
    assert fmt.create_stream_parser() is not None
    assert fmt.validate('{"dialog":[{"character_name":"Alice","sprite":"01","speech":"Hi"}]}')
    assert not fmt.validate("")
    assert not fmt.can_parse("not json")
    assert fmt.parse_complete("") == []
    assert fmt.parse_complete('```json\n{"dialog":[{"character_name":"Alice","sprite":"01","speech":"Hi","transition":"fade-black","motion":"flinch"}]}\n```')[0].transition == "fade_black"
    assert fmt.parse_complete('prefix {"dialog":[{"character_name":"Alice","sprite":"01","speech":"Hi"}]} suffix')[0].name == "Alice"
    assert fmt.parse_complete('[{"character_name":"Alice","sprite":"01","speech":"Hi"}]')[0].name == "Alice"
    assert fmt.parse_complete('{"character_name":"Alice","sprite":"01","speech":"Hi"}')[0].name == "Alice"
    assert fmt.parse_complete("completely broken {json") == []
    assert fmt.parse_complete('{"dialog":[123, {"speech": 999}]}') == []

    serialized = fmt.serialize(
        [
            LLMDialogMessage(
                character_name="Alice",
                sprite="01",
                vibe="calm",
                speech="Hi",
                translate="嗨",
                effect="glow",
                outfit="casual",
                transition="fade",
                motion="nod",
            )
        ]
    )
    assert serialized is not None and '"transition": "fade"' in serialized and '"motion": "nod"' in serialized
    assert fmt.can_parse(serialized)


def test_registry_validation_and_error_guards() -> None:
    with pytest.raises(ValueError):
        register_dialog_format(XmlTagsDialogFormat(), builtin=False)

    class _EmptyIdFormat(_DummyScriptFormat):
        format_id = ""

    with pytest.raises(ValueError):
        register_dialog_format(_EmptyIdFormat())

    class _MismatchFormat(_DummyScriptFormat):
        format_id = "other_v1"

    class _BrokenFactoryFormat(_DummyScriptFormat):
        pass

    def _boom():
        raise RuntimeError("boom")

    configure_registered_dialog_formats(
        [
            DialogFormatContribution(format_id="", factory=_DummyScriptFormat),
            DialogFormatContribution(format_id="xml_v1", factory=XmlTagsDialogFormat),
            DialogFormatContribution(format_id="dup_v1", factory=_DummyScriptFormat),
            DialogFormatContribution(format_id="dup_v1", factory=_DummyScriptFormat),
            DialogFormatContribution(format_id="broken_v1", factory=_boom),
            DialogFormatContribution(format_id="badtype_v1", factory=lambda: "not-a-format"),  # type: ignore[arg-type,return-value]
            DialogFormatContribution(format_id="mismatch_v1", factory=_MismatchFormat),
            DialogFormatContribution(format_id="good_v1", factory=lambda: _BrokenFactoryFormat() if False else type("_Good", (_DummyScriptFormat,), {"format_id": "good_v1"})()),
        ]
    )
    assert get_dialog_format("") is None
    assert get_dialog_format("good_v1") is not None
    assert resolve_dialog_format(None).format_id == "json_v1"
    assert resolve_dialog_format("nonexistent_fmt").format_id == "json_v1"
    assert parse_dialog_content("") == []
    assert parse_dialog_content('<say char="Alice" sprite="01">Hi</say>', format_id="xml_v1")[0].name == "Alice"


def test_xml_parser_edge_cases_attributes_comments_and_truncation() -> None:
    parser = XmlTagsStreamParser()
    # Incremental attribute quoting, html comments, leave aliases, unknown tags, trailing buffer
    chunks = [
        "<!-- lead comment -->",
        "<narration motion=nod tr='旁白'>Wind blew.</narration>",
        "<say char='Bob' sprite='LEAVE' />",
        '<say char="Sue" leave="true" sprite="02">Bye</say>',
        "<unknown>kept</unknown>",
        "<say>no-char</say>",
        "<leave />",
        '<cot>thought<say char="Alice" sprite="01">Reply',
    ]
    out: list[LLMDialogMessage] = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.flush())

    assert parser.parse_failures == 2
    assert any(m.name == "NARR" and m.translate == "旁白" and m.motion == "" for m in out)
    assert any(m.name == "Bob" and m.effect == "LEAVE" and str(m.asset_id) == "-1" for m in out)
    assert any(m.name == "Sue" and m.effect == "LEAVE" for m in out)
    assert any(m.name == "COT" and m.text == "thought" for m in out)
    assert any(m.name == "Alice" and m.text == "Reply" for m in out)
    assert parser.accumulated_text
    assert isinstance(parser.unparsed_remainder, str)

    p2 = XmlTagsStreamParser()
    list(p2.feed("<narr>Trailing"))
    assert p2.flush()[0].name == "NARR"

    p3 = XmlTagsStreamParser()
    list(p3.feed("```xml\n  "))
    assert p3.flush() == [] and p3.buffer == ""

    p4 = XmlTagsStreamParser()
    list(p4.feed("plain"))
    assert p4.flush() == [] and p4.buffer == "plain"


def test_pure_core_registry_raises_lookup_error_when_empty() -> None:
    _reset_for_tests(keep_registrar=False)
    try:
        assert registered_dialog_formats() == ()
        assert detect_dialog_format("anything") is None
        with pytest.raises(LookupError, match="No dialog output formats are registered"):
            resolve_dialog_format(None)
    finally:
        configure_builtin_dialog_formats()



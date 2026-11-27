from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

import pytest

from ai.llm.template import PROMPT_CATALOG
import ai.llm.template_generator as legacy
from ai.llm.formats import (
    XmlTagsStreamParser,
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
)
from core.messaging.formats.registry import _reset_for_tests
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogFormatContribution,
    DialogOutputFormat,
    XML_DIALOG_FORMAT_ID,
)
from sdk.messages import LLMDialogMessage


@pytest.fixture(autouse=True)
def _restore_registry():
    _reset_for_tests()
    configure_builtin_dialog_formats()
    yield
    _reset_for_tests()
    configure_builtin_dialog_formats()


def _configure_fake_assets(
    monkeypatch,
    language: str,
    *,
    voice_language: str | None = None,
    sprite_count: int = 1,
) -> None:
    characters = {
        "Alice": SimpleNamespace(
            name="Alice",
            sprites=[object() for _ in range(sprite_count)],
            emotion_tags="happy: 01",
            character_setting="Friendly guide.",
        ),
    }
    background = SimpleNamespace(
        sprites=[object()],
        bg_tags="room: 01",
        bgm_list=["theme.mp3"],
        bgm_tags="theme: 01",
    )
    manager = SimpleNamespace(
        get_character_by_name=lambda name: characters.get(name),
        get_background_by_name=lambda _name: background,
        config=SimpleNamespace(
            system_config=SimpleNamespace(
                ui_language=language,
                voice_language=voice_language or language,
            )
        ),
    )
    monkeypatch.setattr(legacy, "config_manager", manager)
    monkeypatch.setattr(
        legacy,
        "_T",
        lambda key, **kwargs: PROMPT_CATALOG.translate(f"dialog.{key}", locale=language, **kwargs),
    )


@pytest.mark.parametrize("language", ("zh_CN", "en", "ja"))
def test_xml_template_generation_across_all_locales(monkeypatch, language: str) -> None:
    _configure_fake_assets(monkeypatch, language)

    text, warning = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=True,
        use_cg=True,
        use_llm_translation=False,
        use_cot=True,
        use_choice=True,
        use_narration=True,
        use_stat=True,
        output_format=XML_DIALOG_FORMAT_ID,
    )

    assert warning == ""
    assert "<say" in text
    assert "<scene" in text
    assert "transition" in text
    assert "motion" in text
    assert "fade_black" in text
    assert "shake" in text
    assert PROMPT_CATALOG.translate("dialog.closing_xml_tool_protocol", locale=language) in text

    json_text, _ = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=True,
        use_cg=True,
        use_llm_translation=False,
        output_format=DEFAULT_DIALOG_FORMAT_ID,
    )
    assert '"dialog":' in json_text
    assert "<scene" not in json_text


@pytest.mark.parametrize("language", ("zh_CN", "en", "ja"))
def test_xml_opening_schema_tracks_prompt_switches(monkeypatch, language: str) -> None:
    _configure_fake_assets(
        monkeypatch,
        language,
        voice_language="ja" if language != "ja" else "en",
    )
    gen = legacy.TemplateGenerator(output_contract_patches=[])

    # All optional switches disabled + transparent/no background -> <say> + motion only.
    minimal, _ = gen.generate_chat_template(
        selected_characters=["Alice"],
        bg_name="",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        use_cot=False,
        use_choice=False,
        use_narration=False,
        use_stat=False,
        output_format=XML_DIALOG_FORMAT_ID,
    )
    assert "<say " in minimal
    assert "motion=" in minimal
    for forbidden in (
        "<cot>",
        "<scene ",
        "<bgm ",
        "<narr>",
        "<stat>",
        "<cg>",
        "<choice>",
        'effect="',
        "<tr>",
        "transition=",
    ):
        assert forbidden not in minimal

    switch_matrix = [
        ({"use_cot": True}, "<cot>", ("<scene ", "<bgm ", "<narr>", "<stat>", "<cg>", "<choice>", 'effect="', "<tr>")),
        ({"bg_name": "Room"}, "<scene ", ("<cot>", "<narr>", "<stat>", "<cg>", "<choice>", 'effect="', "<tr>")),
        ({"bg_name": "Room"}, "<bgm ", ("<cot>", "<narr>", "<stat>", "<cg>", "<choice>", 'effect="', "<tr>")),
        ({"bg_name": "Room"}, "transition=", ("<cot>", "<narr>", "<stat>", "<cg>", "<choice>", 'effect="', "<tr>")),
        ({"use_effect": True}, 'effect="', ("<cot>", "<scene ", "<bgm ", "<narr>", "<stat>", "<cg>", "<choice>", "<tr>")),
        ({"use_llm_translation": True}, "<tr>", ("<cot>", "<scene ", "<bgm ", "<narr>", "<stat>", "<cg>", "<choice>", 'effect="')),
        ({"use_narration": True}, "<narr>", ("<cot>", "<scene ", "<bgm ", "<stat>", "<cg>", "<choice>", 'effect="', "<tr>")),
        ({"use_stat": True}, "<stat>", ("<cot>", "<scene ", "<bgm ", "<narr>", "<cg>", "<choice>", 'effect="', "<tr>")),
        ({"use_cg": True}, "<cg>", ("<cot>", "<scene ", "<bgm ", "<narr>", "<stat>", "<choice>", 'effect="', "<tr>")),
        ({"use_choice": True}, "<choice>", ("<cot>", "<scene ", "<bgm ", "<narr>", "<stat>", "<cg>", 'effect="', "<tr>")),
    ]
    base_kwargs = {
        "selected_characters": ["Alice"],
        "bg_name": "",
        "use_effect": False,
        "use_cg": False,
        "use_llm_translation": False,
        "use_cot": False,
        "use_choice": False,
        "use_narration": False,
        "use_stat": False,
        "output_format": XML_DIALOG_FORMAT_ID,
    }
    for overrides, expected_token, excluded_tokens in switch_matrix:
        rendered, _ = gen.generate_chat_template(**{**base_kwargs, **overrides})
        assert expected_token in rendered
        for token in excluded_tokens:
            assert token not in rendered


def test_xml_opening_schema_adapts_media_variants(monkeypatch) -> None:
    _configure_fake_assets(monkeypatch, "en", sprite_count=120)
    full_text, _ = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        use_cot=False,
        use_choice=False,
        use_narration=False,
        use_stat=False,
        output_format=XML_DIALOG_FORMAT_ID,
    )
    assert 'sprite="full scene id"' in full_text
    assert 'sprite="full BGM id"' in full_text
    assert 'sprite="full sprite id (-1 to keep)"' in full_text

    vibe_text, _ = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        use_cot=False,
        use_choice=False,
        use_narration=False,
        use_stat=False,
        media_selection_mode="semantic",
        output_format=XML_DIALOG_FORMAT_ID,
    )
    assert 'vibe="place, weather, and mood phrase"' in vibe_text
    assert 'vibe="music mood and tempo phrase"' in vibe_text
    assert 'vibe="expression and pose phrase"' in vibe_text


class _CustomPromptFormat(DialogOutputFormat):
    format_id = "custom_v1"
    label = "Custom DSL"

    def create_stream_parser(self) -> XmlTagsStreamParser:
        return XmlTagsStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        return []

    def validate(self, raw: str) -> bool:
        return True

    def render_schema_hint(self, *, media_field: str, translate_required: bool, locale: str) -> str | None:
        return f"CUSTOM_SCHEMA({media_field},{translate_required},{locale})"

    def render_format_reminder(self, *, locale: str) -> str | None:
        return f"CUSTOM_REMINDER({locale})"


def test_plugin_dialog_format_hooks_render_in_template(monkeypatch) -> None:
    _configure_fake_assets(monkeypatch, "en")

    class _FallbackReminderFormat(_CustomPromptFormat):
        format_id = "custom_fallback_v1"

        def render_format_reminder(self, *, locale: str) -> str | None:
            return None

    configure_registered_dialog_formats(
        [
            DialogFormatContribution(
                format_id="custom_v1",
                factory=_CustomPromptFormat,
                label="Custom DSL",
                plugin_id="custom-plugin",
            ),
            DialogFormatContribution(
                format_id="custom_fallback_v1",
                factory=_FallbackReminderFormat,
                label="Custom Fallback",
                plugin_id="custom-plugin",
            ),
        ]
    )

    text, warning = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        output_format="custom_v1",
    )

    assert warning == ""
    assert "CUSTOM_SCHEMA(sprite,False,en)" in text
    assert "CUSTOM_REMINDER(en)" in text
    assert "JSON" not in text
    assert "XML/HTML" not in text

    fallback_text, fallback_warning = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        output_format="custom_fallback_v1",
    )
    assert fallback_warning == ""
    assert "CUSTOM_SCHEMA(sprite,False,en)" in fallback_text
    assert "JSON" not in fallback_text
    assert "XML/HTML" not in fallback_text

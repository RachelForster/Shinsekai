"""Digests captured from the pre-Composite renderer, before replacing it."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai.llm.template_generator as legacy
from i18n import tr_in_bundle


LANGUAGES = ("zh_CN", "en", "ja")
FLAGS = (
    "use_effect",
    "use_cg",
    "use_llm_translation",
    "use_cot",
    "use_choice",
    "use_narration",
    "use_stat",
)
FIXTURES = Path(__file__).parent / "fixtures"


def render_case(monkeypatch, language, mask):
    characters = {
        "Alice": SimpleNamespace(
            name="Alice",
            sprites=[object()],
            emotion_tags="happy: 01",
            character_setting="Careful observer.\nPrefers short sentences.",
        ),
        "Bob": SimpleNamespace(
            name="Bob",
            sprites=None,
            emotion_tags="",
            character_setting="",
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
                voice_language=(language if mask % 3 == 0 else "yue"),
            )
        ),
    )
    monkeypatch.setattr(legacy, "config_manager", manager)
    monkeypatch.setattr(
        legacy,
        "_T",
        lambda key, **kwargs: tr_in_bundle(f"template_gen.{key}", language, **kwargs),
    )
    monkeypatch.setattr(legacy, "_format_llm_tools_block", lambda: "TOOLS\n")
    options = {name: bool(mask & (1 << index)) for index, name in enumerate(FLAGS)}
    return legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice", "Bob", " Alice "],
        bg_name=(None, "透明场景", "透明背景", "Room")[mask % 4],
        max_speech_chars=80 if mask % 2 else 0,
        max_dialog_items=4 if mask % 3 else 0,
        **options,
    )


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("mask", range(128))
def test_output_matches_original_renderer(monkeypatch, language, mask):
    expected = json.loads((FIXTURES / f"{language}.json").read_text(encoding="utf-8"))
    text, warning = render_case(monkeypatch, language, mask)

    assert warning == ""
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == expected[str(mask)]

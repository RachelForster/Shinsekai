"""Original renderer digests, updated only to remove duplicate field contracts."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.llm.template import PROMPT_CATALOG
import ai.llm.template_generator as legacy


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


def render_case(monkeypatch, language, mask, *, sprite_count=1):
    characters = {
        "Alice": SimpleNamespace(
            name="Alice",
            sprites=[object() for _ in range(sprite_count)],
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
        lambda key, **kwargs: PROMPT_CATALOG.translate(f"dialog.{key}", locale=language, **kwargs),
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
def test_output_matches_deduplicated_renderer(monkeypatch, language, mask):
    expected = json.loads((FIXTURES / f"{language}.json").read_text(encoding="utf-8"))
    text, warning = render_case(monkeypatch, language, mask)

    assert warning == ""
    tool_protocol = PROMPT_CATALOG.translate("dialog.closing_tool_protocol", locale=language)
    assert text.endswith(tool_protocol + "\n")
    # Preserve the original digests: only the new final protocol rule may differ.
    text = text[: -len(tool_protocol + "\n")]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == expected[str(mask)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_large_sprite_catalog_uses_full_ids_in_the_schema_and_rules(monkeypatch, language):
    text, warning = render_case(monkeypatch, language, 0, sprite_count=111)

    assert warning == ""
    assert PROMPT_CATALOG.translate("dialog.json_full_sprite_head_top", locale=language) in text
    assert PROMPT_CATALOG.translate("dialog.r_full_sprite", locale=language) in text
    assert PROMPT_CATALOG.translate("dialog.r_sprite", locale=language) not in text


def test_auto_voice_language_follows_character_prompt_languages(monkeypatch):
    def run(cast_defs):
        char_map = {
            name: SimpleNamespace(
                name=name,
                sprites=[object()],
                emotion_tags="",
                character_setting="Profile",
                prompt_lang=plang,
                prompt_text=ptext,
            )
            for name, plang, ptext in cast_defs
        }
        manager = SimpleNamespace(
            get_character_by_name=lambda n: char_map.get(n),
            get_background_by_name=lambda _n: None,
            config=SimpleNamespace(system_config=SimpleNamespace(ui_language="zh_CN", voice_language="auto")),
        )
        monkeypatch.setattr(legacy, "config_manager", manager)
        monkeypatch.setattr(
            legacy,
            "_T",
            lambda key, **kwargs: PROMPT_CATALOG.translate(f"dialog.{key}", locale="zh_CN", **kwargs),
        )
        monkeypatch.setattr(legacy, "_format_llm_tools_block", lambda: "")
        text, _ = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
            selected_characters=[name for name, _, _ in cast_defs],
            bg_name="",
            use_effect=False,
            use_cg=False,
            use_llm_translation=True,
        )
        return text

    zh_only = run([("寸策", "zh", "")])
    assert '"translate"' not in zh_only

    ja_only = run([("七海", "ja", "")])
    assert "该句台词的日语译文" in ja_only

    mixed = run([("七海", "ja", ""), ("寸策", "", "今天天气不错")])
    assert "该角色参考语音对应的语言（七海:日语，寸策:中文）" in mixed

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.llm.dialog_repair import repair_dialog_output
from ai.llm.template import PROMPT_CATALOG
from ai.llm.template.dialog.renpy_prompts import (
    render_renpy_format_reminder,
    render_renpy_outfit_hint,
    render_renpy_player_hint,
    render_renpy_repair_prompt,
    render_renpy_requirements,
    render_renpy_schema_hint,
)
from ai.llm.template.dialog.sections.player import player_runtime_prompt
from ai.llm.template.session import OUTFIT_CONTEXT_MARKER
import ai.llm.template_generator as legacy
from application.chat.capabilities.outfit import OutfitRuntimeController
from config.models import Character, Sprite
from core.messaging.formats import configure_builtin_dialog_formats
from core.messaging.formats.registry import _reset_for_tests
from sdk.adapters.dialog_format import (
    DialogFormatPromptContext,
    DialogOutfitHintContext,
    DialogPlayerHintContext,
    RENPY_DIALOG_FORMAT_ID,
)
from test.mocks import MockLLMAdapter


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
    has_player: bool = False,
) -> SimpleNamespace:
    alice_sprites = [object() for _ in range(max(1, sprite_count))]
    hero = SimpleNamespace(
        name="Hero",
        sprites=[object()],
        emotion_tags="calm: 01",
        character_setting="Protagonist setting.",
    )
    alice = SimpleNamespace(
        name="Alice",
        sprites=alice_sprites,
        emotion_tags="happy: 01",
        character_setting="Friendly guide.",
        avatar_type="static",
        sprite_groups={"casual": [0], "formal": [1]} if sprite_count > 1 else {},
    )
    chars = {"Alice": alice}
    if has_player:
        chars["Hero"] = hero
    background = SimpleNamespace(
        sprites=[object()],
        bg_tags="room: 01",
        bgm_list=["theme.mp3"],
        bgm_tags="theme: 01",
    )
    manager = SimpleNamespace(
        get_character_by_name=lambda name: chars.get(name),
        get_background_by_name=lambda name: background if name and name != "透明场景" else None,
        config=SimpleNamespace(
            characters=list(chars.values()),
            system_config=SimpleNamespace(
                ui_language=language,
                voice_language=voice_language or language,
            ),
        ),
    )
    monkeypatch.setattr(legacy, "config_manager", manager)
    monkeypatch.setattr(
        legacy,
        "_T",
        lambda key, **kwargs: PROMPT_CATALOG.translate(f"dialog.{key}", locale=language, **kwargs),
    )
    return manager


@pytest.mark.parametrize("language", ("zh_CN", "en", "ja"))
def test_renpy_prompt_tracks_all_template_switches_and_media_modes(
    monkeypatch,
    language: str,
) -> None:
    _configure_fake_assets(
        monkeypatch,
        language,
        voice_language="ja" if language != "ja" else "en",
    )
    gen = legacy.TemplateGenerator(output_contract_patches=[])
    base_kwargs = dict(
        selected_characters=["Alice"],
        bg_name="透明场景",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        use_cot=False,
        use_choice=False,
        use_narration=False,
        use_stat=False,
        output_format=RENPY_DIALOG_FORMAT_ID,
    )
    minimal, warning = gen.generate_chat_template(**base_kwargs)
    assert warning == ""
    assert 'sprite="' in minimal
    assert 'motion="' in minimal
    for forbidden in ("cot:", "scene ", "play music ", "narr ", "stat ", "cg ", "menu:", 'effect="', "| tr ", "with fade", "with <"):
        assert forbidden not in minimal

    switch_matrix = (
        ({"use_cot": True}, "cot:", ("\nscene ", "narr ", "menu:")),
        ({"bg_name": "Room"}, "\nscene ", ("cot:", "narr ", "menu:")),
        ({"use_effect": True}, 'effect="', ("cot:", "\nscene ", "narr ")),
        ({"use_llm_translation": True}, "| tr ", ("cot:", "\nscene ", "narr ")),
        ({"use_narration": True}, 'narr "', ("cot:", "\nscene ", "menu:")),
        ({"use_stat": True}, "stat ", ("cot:", "\nscene ", "menu:")),
        ({"use_cg": True}, "cg ", ("cot:", "\nscene ", "menu:")),
        ({"use_choice": True}, "menu:", ("cot:", "\nscene ", "stat ")),
    )
    for overrides, expected_token, excluded in switch_matrix:
        rendered, _ = gen.generate_chat_template(**{**base_kwargs, **overrides})
        assert expected_token in rendered
        for token in excluded:
            assert token not in rendered

    # Full sprite IDs & semantic mode adapt scene/bgm/say schema lines
    _configure_fake_assets(monkeypatch, language, sprite_count=105)
    full_rendered, _ = gen.generate_chat_template(**{**base_kwargs, "bg_name": "Room"})
    assert "-1" in full_rendered
    vibe_rendered, _ = gen.generate_chat_template(
        **{**base_kwargs, "bg_name": "Room", "media_selection_mode": "semantic"}
    )
    assert 'vibe="' in vibe_rendered and "scene vibe=" in vibe_rendered and "play music vibe=" in vibe_rendered


def test_renpy_runtime_player_prompt(monkeypatch) -> None:
    cfg = _configure_fake_assets(monkeypatch, "en", has_player=True)
    player_hint = player_runtime_prompt(
        cfg,
        "Hero",
        allow_dialogue=False,
        read_speech=True,
        media_selection_mode="indexed",
        output_format=RENPY_DIALOG_FORMAT_ID,
    )
    assert 'Hero [sprite="01"] ""' in player_hint
    assert '"character_name"' not in player_hint


def test_renpy_outfit_context_and_repair_integration(tmp_path: Path) -> None:
    s1 = tmp_path / "a.png"
    s2 = tmp_path / "b.png"
    s1.write_bytes(b"a")
    s2.write_bytes(b"b")
    alice = Character(
        name="Alice",
        color="#66ccff",
        sprite_prefix="alice",
        sprites=[
            Sprite(path=s1, group="default"),
            Sprite(path=s2, group="formal"),
        ],
        sprite_groups=["default", "formal"],
        default_sprite_group="default",
        emotion_tags="happy\nserious\n",
    )
    cfg = SimpleNamespace(
        config=SimpleNamespace(
            characters=[alice],
            system_config=SimpleNamespace(ui_language="en", voice_language="ja"),
        ),
        get_character_by_name=lambda n: alice if n == "Alice" else None,
    )
    controller = OutfitRuntimeController()
    controller.initialize(cfg, character_names=["Alice"], output_format=RENPY_DIALOG_FORMAT_ID)
    rendered = controller.format_before_chat_message()
    assert rendered.startswith(OUTFIT_CONTEXT_MARKER)
    assert 'Alice [sprite="-1", outfit="formal"]' in rendered
    assert '"character_name"' not in rendered

    adapter = MockLLMAdapter(responses=['Alice [sprite="01"] "Recovered!"'])
    repaired = repair_dialog_output(
        adapter,
        "Not valid DSL",
        [{"role": "user", "content": "hi"}],
        {},
        cancelled=lambda: False,
        event_logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None),
        max_attempts=1,
        speaker_requires_media=lambda n: n == "Alice",
        bound_speakers=("Alice",),
        output_format_id=RENPY_DIALOG_FORMAT_ID,
        locale="en",
    )
    assert repaired == 'Alice [sprite="01"] "Recovered!"'
    prompt_sent = adapter.call_history[0]["messages"][-1]["content"]
    assert "Ren'Py-style DSL" in prompt_sent and "Alice" in prompt_sent


@pytest.mark.parametrize("language", ("zh_CN", "en", "ja"))
def test_renpy_catalog_sections_isolate_untrusted_braces_across_locales(
    language: str,
) -> None:
    hostile_name = "Hero{0}{injected_name}"
    hostile_setting = "Line with {missing_key} and {1} literal braces"
    hostile_cast = "Alice{bad}, Bob{0}"

    # Schema examples in canonical PromptCatalog must stay well-formed across all 3 locales
    for key in ("renpy_example_scene_indexed", "renpy_example_scene_full", "renpy_example_scene_vibe"):
        example = PROMPT_CATALOG.translate(f"dialog.{key}", locale=language)
        assert "[with " not in example

    schema = render_renpy_schema_hint(
        media_field="sprite",
        translate_required=True,
        locale=language,
    )
    assert 'sprite="' in schema and len(schema) > 20

    reqs = render_renpy_requirements(
        DialogFormatPromptContext(locale=language, names=hostile_cast, use_cot=True)
    )
    cname_req = next(spec for spec in reqs if spec.id == "r_cname")
    assert hostile_cast in cname_req.text

    for allow_dialogue in (True, False):
        hint = render_renpy_player_hint(
            DialogPlayerHintContext(
                locale=language,
                name=hostile_name,
                setting=hostile_setting,
                uses_vibe=False,
                allow_player_dialogue=allow_dialogue,
                read_player_speech=True,
                target_voice_name="English",
                portrait_field="sprite",
                portrait_value="01",
            )
        )
        assert hostile_name in hint and hostile_setting in hint

    repair = render_renpy_repair_prompt(
        media_field="sprite",
        retry=True,
        locale=language,
        allow_unbound_speakers=True,
        bound_speakers=(hostile_name,),
    )
    assert hostile_name in repair

    reminder = render_renpy_format_reminder(locale=language)
    outfit_hint = render_renpy_outfit_hint(
        DialogOutfitHintContext(
            locale=language,
            auto_switch_enabled=True,
            example_character=hostile_name,
            example_target_group="summer{0}",
            example_speech="Hi {0}",
        )
    )
    assert reminder and outfit_hint.rule_text and "summer{0}" in outfit_hint.example_line

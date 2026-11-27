"""Tests for expanded DialogOutputFormat SDK hooks, host wiring, and built-in registration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.llm.dialog_repair import repair_dialog_output
from ai.llm.template import PROMPT_CATALOG
from ai.llm.template.dialog.sections.player import player_runtime_prompt
from ai.llm.template.session import OUTFIT_CONTEXT_MARKER
import ai.llm.template_generator as legacy
from application.chat.capabilities.outfit import OutfitRuntimeController
from application.chat.dialog_formats import list_dialog_formats, resolve_outfit_format_hint
from config.models import Character, Sprite
from core.messaging.formats import (
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
    is_builtin_dialog_format,
    resolve_dialog_format,
)
from core.messaging.formats.registry import _reset_for_tests
import plugin_system.host.builtin_plugins as builtin_plugins
from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogFormatContribution,
    DialogFormatPromptContext,
    DialogOutfitHint,
    DialogOutfitHintContext,
    DialogOutputFormat,
    DialogPlayerHintContext,
    DialogStreamParser,
    XML_DIALOG_FORMAT_ID,
)
from sdk.messages import LLMDialogMessage
from sdk.types import OutputContractPatch, RequirementPatch, RequirementSpec
from test.mocks import MockLLMAdapter


class _DummyStreamParser:
    def __init__(self) -> None:
        self.accumulated_text = ""
        self.parse_failures = 0
        self.last_error = ""

    @property
    def has_errors(self) -> bool:
        return self.parse_failures > 0

    @property
    def unparsed_remainder(self) -> str:
        return ""

    def feed(self, chunk: str):
        self.accumulated_text += chunk
        return iter(())

    def flush(self) -> list[LLMDialogMessage]:
        return []

    def format_last_error(self, *, locale: str | None = None) -> str:
        return f"[{locale or 'zh_CN'}] {self.last_error}"


class _FullHooksFormat(DialogOutputFormat):
    format_id = "full_hooks_v1"
    label = "Full Hooks DSL"

    def create_stream_parser(self) -> DialogStreamParser:
        return _DummyStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        return []

    def validate(self, raw: str) -> bool:
        return raw.strip().startswith("VALID:")

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None:
        assert prompt_context is not None
        return f"HOOK_SCHEMA(cot={prompt_context.use_cot},narr={prompt_context.use_narration},mf={media_field})"

    def render_requirements(
        self,
        prompt_context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None:
        return [
            RequirementSpec(id="r_format", text="HOOK_REQ_FORMAT", order=10),
            RequirementSpec(id="r_effect", text="HOOK_REQ_EFFECT", order=170, enabled=prompt_context.use_effect),
            RequirementSpec(id="r_speech", text="HOOK_REQ_SPEECH", order=70),
        ]

    def render_outfit_hint(self, context: DialogOutfitHintContext) -> DialogOutfitHint | None:
        if not context.auto_switch_enabled:
            return DialogOutfitHint(rule_text="HOOK_OUTFIT_LOCKED", example_line="")
        return DialogOutfitHint(
            rule_text="HOOK_OUTFIT_RULE",
            example_line=f"{context.example_character} [outfit={context.example_target_group}] {context.example_speech}",
        )

    def render_player_hint(self, context: DialogPlayerHintContext) -> str | None:
        return f"HOOK_PLAYER({context.name},{context.allow_player_dialogue},{context.portrait_field}={context.portrait_value})"

    def render_format_reminder(self, *, locale: str) -> str | None:
        return f"HOOK_REMINDER({locale})"

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None:
        return f"HOOK_REPAIR(sel={allow_unbound_speakers},speakers={','.join(bound_speakers)})"


class _LegacyMinimalFormat(DialogOutputFormat):
    format_id = "legacy_min_v1"
    label = "Legacy Minimal"

    def create_stream_parser(self) -> DialogStreamParser:
        return _DummyStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        return []

    def validate(self, raw: str) -> bool:
        return raw.strip().startswith("VALID:")

    def render_schema_hint(self, *, media_field: str, translate_required: bool, locale: str) -> str | None:
        return f"LEGACY_SCHEMA({media_field},{translate_required},{locale})"

    def render_repair_prompt(self, *, media_field: str, retry: bool, locale: str) -> str | None:
        return f"LEGACY_REPAIR({media_field},{retry},{locale})"


class _BlankOutfitFormat(_LegacyMinimalFormat):
    format_id = "blank_outfit_v1"

    def render_outfit_hint(self, context: DialogOutfitHintContext) -> DialogOutfitHint | None:
        del context
        return DialogOutfitHint(rule_text="   ", example_line="ignored")


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
    has_player: bool = False,
) -> SimpleNamespace:
    hero = SimpleNamespace(
        name="Hero",
        sprites=[object()],
        emotion_tags="calm: 01",
        character_setting="Protagonist setting.",
    )
    alice = SimpleNamespace(
        name="Alice",
        sprites=[object()],
        emotion_tags="happy: 01",
        character_setting="Friendly guide.",
        avatar_type="static",
        sprite_groups={},
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
            system_config=SimpleNamespace(ui_language=language, voice_language=language),
        ),
    )
    monkeypatch.setattr(legacy, "config_manager", manager)
    monkeypatch.setattr(
        legacy,
        "_T",
        lambda key, **kwargs: PROMPT_CATALOG.translate(f"dialog.{key}", locale=language, **kwargs),
    )
    return manager


def test_full_and_legacy_custom_dialog_format_hooks(monkeypatch) -> None:
    cfg = _configure_fake_assets(monkeypatch, "en", has_player=True)
    configure_registered_dialog_formats(
        [
            DialogFormatContribution("full_hooks_v1", _FullHooksFormat, plugin_id="p1"),
            DialogFormatContribution("legacy_min_v1", _LegacyMinimalFormat, plugin_id="p2"),
            DialogFormatContribution("blank_outfit_v1", _BlankOutfitFormat, plugin_id="p3"),
        ]
    )

    # Base DialogOutputFormat defaults return None on JsonDialogFormat
    json_fmt = resolve_dialog_format(DEFAULT_DIALOG_FORMAT_ID)
    assert json_fmt.render_schema_hint(media_field="sprite", translate_required=False, locale="en") is None
    assert json_fmt.render_requirements(DialogFormatPromptContext()) is None
    assert json_fmt.render_outfit_hint(DialogOutfitHintContext()) is None
    assert json_fmt.render_player_hint(DialogPlayerHintContext()) is None
    assert json_fmt.render_format_reminder(locale="en") is None
    assert json_fmt.render_repair_prompt(media_field="sprite", retry=False, locale="en") is None

    patch = OutputContractPatch(
        id="tighten_speech",
        target_contract="dialog",
        requirement_patches={"r_speech": RequirementPatch(mode="append", text="PATCHED")},
        remove_fields=("effect",),
    )
    rendered, warning = legacy.TemplateGenerator(output_contract_patches=[patch]).generate_chat_template(
        selected_characters=["Alice", "Hero"],
        bg_name="Room",
        use_effect=True,
        use_cg=False,
        use_llm_translation=False,
        use_cot=True,
        use_narration=False,
        player_character="Hero",
        output_format="full_hooks_v1",
    )
    assert warning == ""
    assert "HOOK_SCHEMA(cot=True,narr=False,mf=sprite)" in rendered
    assert "HOOK_REQ_FORMAT" in rendered
    assert "HOOK_REQ_SPEECH PATCHED" in rendered
    assert "HOOK_REQ_EFFECT" not in rendered
    assert "HOOK_PLAYER(Hero,True,sprite=01)" in rendered
    assert "search_tools" in rendered or "r_user_display_name_tool" in rendered or "get_user_info" in rendered

    runtime_player = player_runtime_prompt(
        cfg,
        "Hero",
        allow_dialogue=False,
        read_speech=True,
        media_selection_mode="indexed",
        output_format="full_hooks_v1",
    )
    assert "HOOK_PLAYER(Hero,False,sprite=01)" in runtime_player
    assert legacy.format_reminder("full_hooks_v1", locale="en").startswith("HOOK_REMINDER(en)")

    legacy_rendered, _ = legacy.TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        selected_characters=["Alice"],
        bg_name="Room",
        use_effect=False,
        use_cg=False,
        use_llm_translation=False,
        output_format="legacy_min_v1",
    )
    assert "LEGACY_SCHEMA(sprite,False,en)" in legacy_rendered

    # Selective repair supports both 5-arg and legacy 3-arg hooks without TypeError.
    adapter_full = MockLLMAdapter(responses=["bad"])
    repair_dialog_output(
        adapter_full,
        "bad",
        [{"role": "user", "content": "hi"}],
        {},
        cancelled=lambda: False,
        event_logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None),
        max_attempts=1,
        speaker_requires_media=lambda n: n == "Alice",
        bound_speakers=("Alice",),
        output_format_id="full_hooks_v1",
        locale="en",
    )
    sent_full = "\n".join(str(m.get("content") or "") for m in adapter_full.call_history[0]["messages"])
    assert "HOOK_REPAIR(sel=True,speakers=Alice)" in sent_full

    adapter_legacy = MockLLMAdapter(responses=["bad"])
    repair_dialog_output(
        adapter_legacy,
        "bad",
        [{"role": "user", "content": "hi"}],
        {},
        cancelled=lambda: False,
        event_logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None),
        max_attempts=1,
        speaker_requires_media=lambda n: n == "Alice",
        bound_speakers=("Alice",),
        output_format_id="legacy_min_v1",
        locale="en",
    )
    sent_legacy = "\n".join(str(m.get("content") or "") for m in adapter_legacy.call_history[0]["messages"])
    assert "LEGACY_REPAIR(sprite,False,en)" in sent_legacy


def test_outfit_hook_routing_and_builtin_plugin_guards(tmp_path: Path, monkeypatch, caplog) -> None:
    configure_registered_dialog_formats(
        [
            DialogFormatContribution("full_hooks_v1", _FullHooksFormat, plugin_id="p1"),
            DialogFormatContribution("blank_outfit_v1", _BlankOutfitFormat, plugin_id="p2"),
        ]
    )

    s1 = tmp_path / "a.png"
    s2 = tmp_path / "b.png"
    s1.write_bytes(b"a")
    s2.write_bytes(b"b")
    alice = Character(
        name="Alice",
        color="#66ccff",
        sprite_prefix="alice",
        sprites=[Sprite(path=s1, group="default"), Sprite(path=s2, group="formal")],
        sprite_groups=["default", "formal"],
        default_sprite_group="default",
        emotion_tags="happy\n",
    )
    cfg = SimpleNamespace(
        config=SimpleNamespace(
            characters=[alice],
            system_config=SimpleNamespace(ui_language="en", voice_language="ja"),
        ),
        get_character_by_name=lambda n: alice if n == "Alice" else None,
    )
    controller = OutfitRuntimeController()
    controller.initialize(cfg, character_names=["Alice"], output_format="full_hooks_v1")
    rendered = controller.format_before_chat_message()
    assert rendered.startswith(OUTFIT_CONTEXT_MARKER)
    assert "HOOK_OUTFIT_RULE" in rendered and "Alice [outfit=formal]" in rendered

    assert resolve_outfit_format_hint(
        output_format="full_hooks_v1",
        locale="en",
        media_selection_mode="indexed",
        auto_switch_enabled=False,
    ) == ("HOOK_OUTFIT_LOCKED", "")
    assert resolve_outfit_format_hint(
        output_format="blank_outfit_v1",
        locale="en",
        media_selection_mode="indexed",
        auto_switch_enabled=True,
    ) == ("", "")
    assert resolve_outfit_format_hint(
        output_format=XML_DIALOG_FORMAT_ID,
        locale="en",
        media_selection_mode="indexed",
        auto_switch_enabled=True,
    ) == ("", "")

    assert is_builtin_dialog_format(XML_DIALOG_FORMAT_ID) is True
    assert is_builtin_dialog_format("full_hooks_v1") is False
    by_id = {row["id"]: row for row in list_dialog_formats()}
    assert by_id[XML_DIALOG_FORMAT_ID]["builtin"] is True
    assert by_id["full_hooks_v1"]["builtin"] is False

    # External plugin overriding a builtin id fails, while shinsekai.builtin.* does not log error.
    with caplog.at_level("ERROR"):
        configure_registered_dialog_formats(
            [DialogFormatContribution(XML_DIALOG_FORMAT_ID, _FullHooksFormat, plugin_id="third_party.plugin")]
        )
    assert any("conflicts with builtin" in rec.message for rec in caplog.records)
    caplog.clear()
    class _BuiltinXmlFormat(_FullHooksFormat):
        format_id = XML_DIALOG_FORMAT_ID

    with caplog.at_level("ERROR"):
        configure_registered_dialog_formats(
            [DialogFormatContribution(XML_DIALOG_FORMAT_ID, _BuiltinXmlFormat, plugin_id="shinsekai.builtin.xml")]
        )
    assert not caplog.records

    # register_builtin_plugins tolerates non-PluginManager mocks and registers configured classes.
    builtin_plugins.register_builtin_plugins(object())
    seen: list[type] = []
    fake_cls = type("_FakePlugin", (), {})
    monkeypatch.setattr(builtin_plugins, "BUILTIN_PLUGIN_CLASSES", (fake_cls,))
    builtin_plugins.register_builtin_plugins(SimpleNamespace(register_plugin_class=seen.append))
    assert seen == [fake_cls]

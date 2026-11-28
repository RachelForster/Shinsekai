"""Unit tests for the split presentation helpers, effect resolution, and controllers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from application.chat.presentation.ambient_controller import (
    StageAmbientController,
    fold_ambient_directives,
)
from application.chat.presentation.dialog_controller import StageDialogController
from application.chat.presentation.effect_controller import StageEffectController
from application.chat.presentation.effect_resolution import (
    EffectCatalog,
    EffectDirective,
    parse_effect_directive,
    resolve_effect_assets,
    should_skip_for_timing,
)
from application.chat.presentation.sprite_controller import StageSpriteController
from core.effects import AmbientEffectAsset, ImageEffectAsset

REPO_ROOT = Path(__file__).resolve().parents[4]
PRESENTATION_DIR = REPO_ROOT / "application" / "chat" / "presentation"


class _Urls:
    def media_url(self, raw_path: str) -> str:
        return f"media://{raw_path}"

    def avatar_url(self, model_path: str, path: str) -> str:
        return f"avatar://{model_path}/{path}"


def test_parse_effect_directive_handles_modes_and_prefixes() -> None:
    assert parse_effect_directive("") is None
    assert parse_effect_directive("   ") is None
    assert parse_effect_directive("leave") == EffectDirective(mode="leave", keyword="")
    assert parse_effect_directive("AMBIENT-STOP-ALL") == EffectDirective(
        mode="ambient-stop-all", keyword=""
    )
    assert parse_effect_directive("ambient: rain ") == EffectDirective(
        mode="ambient", keyword="rain"
    )
    assert parse_effect_directive("shelter:rain") == EffectDirective(
        mode="shelter", keyword="rain"
    )
    assert parse_effect_directive("expose:mist") == EffectDirective(
        mode="expose", keyword="mist"
    )
    assert parse_effect_directive("ambient-stop:rain") == EffectDirective(
        mode="ambient-stop", keyword="rain"
    )
    assert parse_effect_directive("loop: rain") == EffectDirective(mode="loop", keyword="rain")
    assert parse_effect_directive("stop:rain") == EffectDirective(mode="stop", keyword="rain")
    assert parse_effect_directive("before: bang ") == EffectDirective(
        mode="once", keyword="bang", timing="before"
    )
    assert parse_effect_directive("after: bang ") == EffectDirective(
        mode="once", keyword="bang", timing="after"
    )
    assert parse_effect_directive("LOOP:rain") == EffectDirective(
        mode="once", keyword="LOOP:rain", timing="before"
    )


@pytest.mark.parametrize(
    ("directive", "after_dialog", "expected"),
    [
        (EffectDirective(mode="once", keyword="k", timing="before"), False, False),
        (EffectDirective(mode="once", keyword="k", timing="before"), True, True),
        (EffectDirective(mode="once", keyword="k", timing="after"), False, True),
        (EffectDirective(mode="once", keyword="k", timing="after"), True, False),
        (EffectDirective(mode="loop", keyword="k"), True, False),
        (EffectDirective(mode="ambient", keyword="k"), True, False),
        (EffectDirective(mode="leave", keyword=""), False, False),
    ],
)
def test_should_skip_for_timing(
    directive: EffectDirective, after_dialog: bool, expected: bool
) -> None:
    assert should_skip_for_timing(directive, after_dialog=after_dialog) is expected


def test_resolve_effect_assets_prioritizes_exact_and_image_bound_audio() -> None:
    catalog = EffectCatalog(
        audio_map={"shocked_custom": "custom.wav", "雨天": "rain.wav"},
        image_map={
            "key": ImageEffectAsset("key.png", "pickup.wav"),
            "被查验者为“狼”": ImageEffectAsset("wolf.png", ""),
        },
        ambient_map={"fog": AmbientEffectAsset("fog.png", "", "back")},
    )

    builtin = resolve_effect_assets("shocked", catalog)
    assert builtin.audio_path == "./assets/system/sound/shocked.wav"
    assert builtin.audio_key == "shocked"

    exact_with_bound = resolve_effect_assets("key", catalog)
    assert exact_with_bound.image_key == "key"
    assert exact_with_bound.image_path == "key.png"
    assert exact_with_bound.audio_path == "pickup.wav"

    fuzzy = resolve_effect_assets("查验结果为狼", catalog)
    assert fuzzy.image_key == "被查验者为“狼”"
    assert fuzzy.image_path == "wolf.png"


def test_fold_ambient_directives_tracks_aliases_replacement_and_stop(tmp_path) -> None:
    rain = str(tmp_path / "rain.webm")
    storm = str(tmp_path / "storm.webm")
    fog = str(tmp_path / "fog.png")
    ambient_map = {
        "rain": AmbientEffectAsset(rain, "", "back"),
        "drizzle": AmbientEffectAsset(rain, "", "back"),
        "storm": AmbientEffectAsset(storm, "", "front"),
        "fog": AmbientEffectAsset(fog, "", "back"),
    }

    folded = fold_ambient_directives(
        [
            "ambient:rain",
            "expose:drizzle",
            "ambient:fog",
            "ambient-stop:drizzle",
            "shelter:fog",
        ],
        ambient_map,
    )
    assert list(folded) == ["fog"]
    assert folded["fog"]["layer"] == "back"

    replaced = fold_ambient_directives(["ambient:rain", "AMBIENT-STOP-ALL", "expose:storm"], ambient_map)
    assert list(replaced) == ["storm"]
    assert replaced["storm"]["layer"] == "front"


def test_stage_ambient_controller_manages_lifecycle_without_runtime_patch(tmp_path) -> None:
    events: list[dict] = []
    rain = AmbientEffectAsset(str(tmp_path / "rain.webm"), str(tmp_path / "rain.wav"), "back")
    snow = AmbientEffectAsset(str(tmp_path / "snow.webm"), "", "front")
    controller = StageAmbientController(
        emit=events.append,
        media_url=lambda path: f"media://{path}",
        catalog_provider=lambda: EffectCatalog(ambient_map={"rain": rain, "snow": snow}),
    )

    assert controller.start_ambient_effect("rain", rain) is True
    assert controller.start_ambient_effect("rain", rain) is False
    assert controller.start_ambient_effect("rain", rain, layer="front") is True
    assert controller.start_ambient_effect("rain", snow) is True
    assert [e["type"] for e in events] == [
        "ambient.start",
        "ambient.layer",
        "ambient.stop",
        "ambient.start",
    ]

    controller.restore_ambient_directives(["ambient:rain", "expose:snow"])
    assert events[-3] == {"type": "ambient.stop-all"}
    assert events[-2]["type"] == "ambient.start"
    assert events[-2]["key"] == "rain"
    assert events[-2]["layer"] == "back"
    assert events[-1]["type"] == "ambient.start"
    assert events[-1]["key"] == "snow"
    assert events[-1]["layer"] == "front"


def test_stage_effect_controller_resolves_directives_via_injected_catalog() -> None:
    events: list[dict] = []
    removed: list[str] = []
    catalog = EffectCatalog(
        audio_map={"rain": "rain.wav", "alias": "rain.wav"},
        image_map={"key": ImageEffectAsset("key.png", "pickup.wav")},
        ambient_map={"fog": AmbientEffectAsset("fog.png", "", "back")},
    )
    controller = StageEffectController(
        emit=events.append,
        media_url=lambda path: f"media://{path}",
        remove_sprite=removed.append,
        catalog_provider=lambda: catalog,
    )

    assert controller.resolve_effect("LEAVE", {"character_name": "Mio"}, after_dialog=False)
    assert removed == []
    assert controller.resolve_effect("LEAVE", {"character_name": "Mio"}, after_dialog=True)
    assert removed == ["Mio"]

    assert controller.resolve_effect("before:", {}, after_dialog=True) is True
    assert controller.resolve_effect("before:", {}, after_dialog=False) is False
    assert controller.resolve_effect("loop:", {}, after_dialog=False) is False
    assert controller.resolve_effect("loop:key", {}, after_dialog=False) is False

    assert controller.resolve_effect("loop:rain", {}, after_dialog=False) is True
    controller.start_loop_effect("alias", "rain.wav")
    assert controller.resolve_effect("stop:rain", {}, after_dialog=False) is True
    assert controller.looping_effects == {}
    assert [e for e in events if e["type"] == "effect.loop.stop"] == [
        {"type": "effect.loop.stop", "key": "rain"},
        {"type": "effect.loop.stop", "key": "alias"},
    ]

    assert controller.resolve_effect("expose:fog", {}, after_dialog=False) is True
    assert controller.resolve_effect("AMBIENT-STOP-ALL", {}, after_dialog=False) is True
    assert controller.resolve_effect("ambient-stop:fog", {}, after_dialog=False) is False


def test_stage_sprite_controller_lru_removal_reaction_and_motion() -> None:
    events: list[dict] = []
    characters = {
        "mio": SimpleNamespace(name="Mio", sprites=[{"path": "a.png"}]),
        "ren": SimpleNamespace(name="Ren", sprites=[{"path": "b.png"}]),
        "aoi": SimpleNamespace(name="Aoi", sprites=[{"path": "c.png"}]),
    }
    sprites = StageSpriteController(
        emit=events.append,
        resource_urls=_Urls(),
        max_sprite_slots=2,
        character_lookup=lambda name: characters.get(name.casefold()),
        visual_resolver=lambda ch, idx, urls: SimpleNamespace(
            event_fields=lambda: {
                "url": urls.media_url(ch.sprites[idx]["path"]),
                "avatarType": "static",
                "modelUrl": "",
                "scale": 1.0,
                "identityKey": f"character:{ch.name.casefold()}",
            }
        ),
    )

    sprites.update_sprite("Mio", 0)
    sprites.update_sprite("Ren", 0)
    sprites.update_sprite("Mio", 0)
    sprites.update_sprite("Aoi", 0)
    assert list(sprites.sprite_lru.items()) == [("Mio", 0), ("Aoi", 1)]

    sprites.remove_character_sprite("MIO")
    assert list(sprites.sprite_lru.items()) == [("Aoi", 1)]
    assert events[-1] == {"type": "sprite.remove", "characterName": "Mio"}

    sprites.post_sprite_reaction("   ", "ignored")
    sprites.post_sprite_reaction("Aoi", "x" * 100, duration_ms=100)
    assert events[-1] == {
        "type": "sprite.reaction",
        "characterName": "Aoi",
        "text": "x" * 80,
        "durationMs": 800,
    }

    sprites.post_sprite_motion("Aoi", "bounce")
    assert events[-1]["type"] == "sprite.motion"
    assert events[-1]["motion"] == "bounce"
    count_before = len(events)
    sprites.post_sprite_motion("Aoi", "invalid_motion_xyz")
    assert len(events) == count_before


def test_stage_dialog_controller_portrait_deferral_and_history_sync() -> None:
    events: list[dict] = []
    history: list[str] = []
    portraits: list[tuple[str, int]] = []
    dialog = StageDialogController(
        emit=events.append,
        chat_history_getter=lambda: history,
        voice_archive_getter=lambda: None,
        player_character_getter=lambda: "神羽",
        show_player_portrait=lambda name, sid: portraits.append((name, sid)),
        record_console_user_message=lambda text: history.append(f"<p>{text}</p>"),
    )

    dialog.queue_player_portrait("神羽", 2)
    dialog.post_dialog_html("<p><b>NARR</b>：<span>神羽</span>抬起头。</p>", speaker="NARR")
    assert portraits == [("神羽", 2)]

    events.clear()
    dialog.queue_player_portrait("神羽", 3)
    dialog.update_dialog("Mio", "你好", "#ffffff", False, animate=False)
    assert len(history) == 1
    assert [e["type"] for e in events] == ["dialog.end"]
    assert events[-1]["animate"] is False

    # Deferred portrait is discarded when an unrelated NPC speaks next.
    dialog.update_dialog("Mio", "看这里", "#ffffff", False)
    assert portraits == [("神羽", 2)]
    assert [e["type"] for e in events] == ["dialog.end", "dialog.end", "history.replace"]


def test_split_presentation_modules_stay_compact() -> None:
    updates_lines = len((PRESENTATION_DIR / "updates.py").read_text(encoding="utf-8").splitlines())
    assert updates_lines <= 350

    for filename in (
        "ambient_controller.py",
        "character_lookup.py",
        "dialog_controller.py",
        "effect_controller.py",
        "effect_resolution.py",
        "formatting.py",
        "headless.py",
        "sprite_controller.py",
    ):
        line_count = len((PRESENTATION_DIR / filename).read_text(encoding="utf-8").splitlines())
        assert line_count <= 250, f"{filename} unexpectedly grew to {line_count} lines"

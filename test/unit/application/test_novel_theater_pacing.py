"""Regression tests for novel stage speaker display names and runtime NARR pacing."""

from __future__ import annotations

from queue import Queue
import threading
from types import SimpleNamespace
from typing import Any

from application.chat.presentation.handlers.character_media import CharacterMediaHandler
from application.chat.presentation.handlers.presentation import CharacterDialogUiHandler
from application.chat.presentation.updates import StreamingUIUpdateManager
from application.novel_theater.casting import casting_map_from_novel_state
from application.novel_theater.narration_pacing import split_long_narration_dialogs
from application.novel_theater.turn_delivery import deliver_dialogs_to_stage
from application.session_behavior.casting import CastBinding, CastingMap
from core.messaging.chat_turn_service import ChatTurnService
from sdk.messages import LLMDialogMessage, PresentationMessage


def test_bound_novel_character_displays_story_name_across_sprite_dialog_and_effects(
    monkeypatch,
    tmp_path,
) -> None:
    casting = CastingMap(
        (
            CastBinding(
                character_name="Alice",
                display_name="叶文洁",
                aliases=("叶文洁", "小叶"),
            ),
            CastBinding(
                character_name="Alice",
                display_name="程心",
                aliases=("程心",),
            ),
        )
    )
    alice_cfg = SimpleNamespace(
        name="Alice",
        color="#ffaa00",
        speech_volume=1.0,
        sprites=[{"path": "sprites/alice_0.png"}],
        sprite_groups={},
        portrait_crop=None,
    )
    cfg = SimpleNamespace(
        refresh_media_catalogs=lambda: None,
        get_character_by_name=lambda n: alice_cfg if n == "Alice" else None,
        config=SimpleNamespace(effect_list=[]),
    )
    emitted: list[dict[str, Any]] = []
    pres_queue: Queue[PresentationMessage] = Queue()
    played: list[str] = []

    ui = StreamingUIUpdateManager(
        SimpleNamespace(emit=emitted.append),
        resource_urls=SimpleNamespace(
            media_url=lambda p: f"/media?p={p}",
            avatar_url=lambda m, p: f"/avatar?m={m}&p={p}",
        ),
    )
    controller = SimpleNamespace(
        play_and_wait=lambda *, character_name, **_kw: (
            played.append(character_name),
            SimpleNamespace(error=""),
        )[1],
        wait_interruptibly=lambda _secs: None,
    )
    rt = SimpleNamespace(
        opencc=SimpleNamespace(convert=lambda s: s),
        config=cfg,
        presentation_queue=pres_queue,
        ui_update_manager=ui,
        ui_playback=SimpleNamespace(
            playback_controller=controller,
            task_done_requested=threading.Event(),
        ),
        tts_manager=None,
        player_character="",
        read_player_speech=False,
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.character_media.get_app_runtime",
        lambda: rt,
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.presentation.get_app_runtime",
        lambda: rt,
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.presentation.get_character_by_name",
        lambda n: alice_cfg if n == "Alice" else None,
    )
    monkeypatch.setattr(
        "application.chat.presentation.updates.get_character_by_name",
        lambda n: alice_cfg if n == "Alice" else None,
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.character_media.resolve_character_visual",
        lambda _cfg, _idx, _urls: SimpleNamespace(
            event_fields=lambda: {"path": "/media?p=alice_0.png"}
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "application.chat.presentation.updates.resolve_character_visual",
        lambda _cfg, _idx, _urls: SimpleNamespace(
            event_fields=lambda: {
                "identityKey": "alice",
                "url": "/media?p=alice_0.png",
                "scale": 1.0,
                "x": 0.0,
                "y": 0.0,
            }
        ),
    )

    sprite_mock = SimpleNamespace(
        candidates=lambda _cfg: (SimpleNamespace(asset_id="0", tags="calm", path="sprites/alice_0.png"),),
        resolve=lambda _cfg, _cands, _req: SimpleNamespace(
            found=True, asset_id="1", voice_type="", voice_path="", voice_text=""
        ),
    )
    tts_calls: list[str] = []

    def _fake_tts(req):
        tts_calls.append(req.character_name)
        wav = tmp_path / f"tts_{req.character_name}.wav"
        wav.write_bytes(b"RIFF")
        return (str(wav),)

    tts_mock = SimpleNamespace(generate=_fake_tts)
    media_handler = CharacterMediaHandler(
        tts_generation_strategy=tts_mock,
        sprite_resolver=sprite_mock,
        casting_map_provider=lambda: casting,
    )
    ui_handler = CharacterDialogUiHandler()

    # Alias "小叶" resolves Alice's sprite/TTS but renders stage events under canonical "叶文洁"
    media_handler.handle(
        LLMDialogMessage(
            character_name="小叶",
            speech="我们收到回信了。",
            sprite="1",
            motion="nod",
            effect="LEAVE",
        )
    )
    out = pres_queue.get_nowait()
    assert out.name == "Alice"
    assert out.display_name == "叶文洁"

    ui_handler.handle(out)
    ui_handler.post_process(out)

    sprite_events = [e for e in emitted if e.get("type") == "sprite.show"]
    dialog_events = [e for e in emitted if e.get("type") == "dialog.end"]
    motion_events = [e for e in emitted if e.get("type") == "sprite.motion"]
    remove_events = [e for e in emitted if e.get("type") == "sprite.remove"]

    assert sprite_events and sprite_events[-1]["characterName"] == "叶文洁"
    assert dialog_events and dialog_events[-1]["speaker"] == "叶文洁"
    assert "叶文洁" in dialog_events[-1]["fullHtml"]
    assert "Alice" not in dialog_events[-1]["fullHtml"]
    assert motion_events and motion_events[-1]["characterName"] == "叶文洁"
    assert remove_events and remove_events[-1]["characterName"] == "叶文洁"
    assert played == ["叶文洁"]


def test_split_long_narration_dialogs_and_delivery_pacing() -> None:
    long_narr = (
        "暮色彻底沉落下来，港口的雾灯一盏接一盏地亮起，潮湿的海风掠过斑驳的铁栏杆。"
        "他在石阶边缘停下脚步，低头望向黑沉沉的海面，远处的汽笛声断断续续地传来。"
        "口袋里的怀表早已经停摆，铜壳上还留着一道细长的划痕。"
    )
    dialogs = [
        {"character_name": "NARR", "speech": long_narr, "sprite": "-1", "effect": "wind"},
        {"character_name": "叶文洁", "speech": "你终于来了。这封信我保存了很多年，一直不敢寄出。" + "。" * 45, "sprite": "1"},
        {"character_name": "旁白", "speech": "夜风微凉，树影轻轻晃动。", "sprite": "-1"},
    ]

    paced = split_long_narration_dialogs(dialogs, max_cjk_chars=65)
    assert len(paced) >= 4
    narr_cards = [d for d in paced if d["character_name"] in {"NARR", "旁白"}]
    speech_cards = [d for d in paced if d["character_name"] == "叶文洁"]

    # First NARR paragraph split into crisp <= 65 char cards with single effect on first card
    assert len(narr_cards) >= 3
    assert all(len(c["speech"]) <= 65 for c in narr_cards)
    assert narr_cards[0]["effect"] == "wind"
    assert all(c["effect"] == "" for c in narr_cards[1:-1])

    # Spoken dialogue is never split even if long
    assert len(speech_cards) == 1
    assert "你终于来了。" in speech_cards[0]["speech"]

    # Delivery through deliver_dialogs_to_stage enqueues all paced items cleanly
    dq: Queue[LLMDialogMessage] = Queue()
    turn_service = ChatTurnService()
    deliver_dialogs_to_stage(
        dialogs,
        dialog_queue=dq,
        presentation_queue=None,
        ui_updates=None,
        chat_turn_service=turn_service,
        history_turn_id="turn-pace-1",
    )
    enqueued = []
    while not dq.empty():
        enqueued.append(dq.get_nowait())
    assert len(enqueued) == len(paced)


def test_legacy_behavior_state_hydrates_display_names_from_cast_entries() -> None:
    legacy_state = {
        "casting": {
            "bindings": [
                {
                    "characterName": "Alice",
                    "aliases": ["叶文洁", "小叶", "程心"],
                    "role": "lead",
                    "silhouetteUntilRevealed": False,
                    "revealed": True,
                }
            ]
        },
        "castEntries": [
            {
                "sourceName": "叶文洁",
                "aliases": ["小叶"],
                "targetCharacter": "Alice",
                "role": "lead",
                "silhouetteUntilRevealed": False,
            },
            {
                "sourceName": "程心",
                "aliases": [],
                "targetCharacter": "Alice",
                "role": "supporting",
                "silhouetteUntilRevealed": False,
            },
        ],
    }

    hydrated = casting_map_from_novel_state(legacy_state)
    ye = hydrated.resolve("小叶")
    assert ye is not None
    assert ye.character_name == "Alice"
    assert ye.display_name == "叶文洁"
    assert hydrated.resolve_display_name("小叶", ye) == "叶文洁"

    cheng = hydrated.resolve("程心")
    assert cheng is not None
    assert cheng.character_name == "Alice"
    assert cheng.display_name == "程心"
    assert hydrated.resolve_display_name("程心", cheng) == "程心"

    assert hydrated.bound_speaker_names() == ("叶文洁", "小叶", "程心")

"""Unit tests for Phase 5 sprite outfit isolation (all 4 pipelines), manual lock, story switch, and rollback."""

from __future__ import annotations

import json
from pathlib import Path
import queue
from types import SimpleNamespace

import pytest

from ai.llm.template_generator import TemplateGenerator
from application.characters.sprite.transition_recommendations import (
    analyze_transition_recommendations,
)
from application.characters.sprite.transition_sprites import transition_identity
from application.chat.capabilities.outfit import (
    OutfitBeforeChatProvider,
    OutfitPersistenceProvider,
    OutfitRuntimeController,
)
from application.chat.dialog_media.catalogs import build_session_asset_catalogs
from application.chat.dialog_media.replay import enqueue_latest_media_replay
from application.chat.dialog_media.lookup import (
    AssetIdMatch,
    AssetLookupRequest,
    AssetLookupResult,
    AssetLookupStrategy,
)
from application.chat.presentation.handlers.dialog_media import CharacterMediaHandler
from application.perception.coordinator import PerceptionCoordinator
from config.schema import Character, Sprite
from core.chat_history.identity import CHAT_TURN_ID
from core.chat_history.models import OutfitState, turn_node_from_message
from core.chat_history.sqlite_session_store import (
    close_all_session_stores,
    open_session_store_for_dir,
)
from core.chat_history.storage import close_session_store
from core.perception.models import PerceptionConfig, ReflexDecision
from core.sprite.transitions import TRANSITION_FRAME_COUNT, valid_transitions
from sdk.hooks import BeforeChatContext, MessageAddedContext
from sdk.messages import LLMDialogMessage


class _FakeConfigManager:
    def __init__(self, characters: list[Character]):
        self.config = SimpleNamespace(
            characters=characters,
            system_config=SimpleNamespace(voice_language="ja", ui_language="zh_CN"),
        )

    def get_character_by_name(self, name: str):
        return next((c for c in self.config.characters if c.name == name), None)

    def get_background_by_name(self, _name: str):
        return None

    def refresh_media_catalogs(self):
        pass


class _TagMatchLookupStrategy(AssetLookupStrategy):
    """Deterministic semantic vibe matcher for unit tests."""

    def lookup(self, request: AssetLookupRequest) -> AssetLookupResult:
        vibe = request.vibe.strip()
        if vibe:
            for cand in request.candidates:
                if vibe in cand.tags:
                    return AssetLookupResult(matches=(AssetIdMatch(asset_id=cand.asset_id),))
            return AssetLookupResult(matches=())
        explicit = request.explicit_asset_id.strip()
        if explicit and explicit != "-1":
            for cand in request.candidates:
                if cand.asset_id == explicit:
                    return AssetLookupResult(matches=(AssetIdMatch(asset_id=cand.asset_id),))
        return AssetLookupResult(matches=())


def _multi_outfit_character(
    tmp_path: Path,
    *,
    fallback_to_default: bool = True,
) -> Character:
    base = tmp_path / "sprites" / "kurisu"
    base.mkdir(parents=True, exist_ok=True)
    files = []
    for fname in (
        "default_calm.png",
        "school_smile.png",
        "school_angry.png",
        "pajama_sleepy.png",
        "pajama_shy.png",
    ):
        p = base / fname
        p.write_bytes(fname.encode())
        files.append(p)

    return Character(
        name="Kurisu",
        color="#c84b31",
        sprite_prefix="kurisu",
        character_setting="天才脑科学少女。",
        sprites=[
            Sprite(path=files[0]),  # idx 0, id '1', group '默认'
            Sprite(path=files[1], group="校服"),  # idx 1, id '2'
            Sprite(path=files[2], group="校服"),  # idx 2, id '3'
            Sprite(path=files[3], group="睡衣"),  # idx 3, id '4'
            Sprite(path=files[4], group="睡衣"),  # idx 4, id '5'
        ],
        sprite_groups=["校服", "睡衣"],
        default_sprite_group="校服",
        fallback_to_default_group=fallback_to_default,
        emotion_tags=(
            "立绘 1：平静，思考\n"
            "立绘 2：微笑，开心\n"
            "立绘 3：生气，脸红\n"
            "立绘 4：困倦，打哈欠\n"
            "立绘 5：害羞，微笑\n"
        ),
    )


def test_pipeline_1_and_2_catalog_scopes_prompt_injection_and_semantic_fallback(
    tmp_path, monkeypatch
):
    char = _multi_outfit_character(tmp_path, fallback_to_default=True)
    cfg = _FakeConfigManager([char])

    catalogs = build_session_asset_catalogs(cfg, ["Kurisu"], None)
    by_scope = {c.scope: [cand.asset_id for cand in c.candidates] for c in catalogs}
    assert by_scope == {
        "sprite:Kurisu:校服": ["2", "3"],
        "sprite:Kurisu:睡衣": ["4", "5"],
        "sprite:Kurisu:默认": ["1"],
    }

    monkeypatch.setattr("ai.llm.template_generator.config_manager", cfg)
    system_prompt, _ = TemplateGenerator(output_contract_patches=[]).generate_chat_template(
        ["Kurisu"],
        "",
        False,
        False,
        False,
    )
    assert "2:微笑，开心" in system_prompt
    assert "3:生气，脸红" in system_prompt
    assert "4:困倦，打哈欠" not in system_prompt

    controller = OutfitRuntimeController()
    controller.initialize(cfg, character_names=["Kurisu"])
    provider = OutfitBeforeChatProvider(controller)
    ctx = BeforeChatContext(
        messages=[{"role": "system", "content": system_prompt}],
        tools=None,
        generation_kwargs={},
        stream=True,
    )
    provider.before_chat(ctx)
    injected = ctx.messages[-1]["content"]
    assert "当前服装分组「校服」" in injected
    assert "2: 微笑，开心" in injected
    assert '"outfit"' in injected

    pres_q: queue.Queue = queue.Queue()
    fake_rt = SimpleNamespace(
        config=cfg,
        outfit_controller=controller,
        opencc=SimpleNamespace(convert=lambda s: s),
        presentation_queue=pres_q,
        tts_manager=None,
        player_character="",
        read_player_speech=False,
        ui_update_manager=SimpleNamespace(hide_busy_bar=lambda: None),
    )
    monkeypatch.setattr(
        "application.chat.presentation.handlers.dialog_media.get_app_runtime",
        lambda: fake_rt,
    )
    handler = CharacterMediaHandler(asset_lookup_strategy=_TagMatchLookupStrategy())

    msg_switch = LLMDialogMessage.model_validate(
        {
            "character_name": "Kurisu",
            "speech": "已经这么晚了，我去换睡衣了。",
            "vibe": "困倦",
            "outfit": "睡衣",
        }
    )
    handler.handle(msg_switch)
    emitted_1 = pres_q.get_nowait()
    assert controller.active_group_for(char) == "睡衣"
    assert emitted_1.asset_id == "4"

    msg_fb = LLMDialogMessage.model_validate(
        {
            "character_name": "Kurisu",
            "speech": "让我想一想这个实验数据……",
            "vibe": "脸红",
        }
    )
    handler.handle(msg_fb)
    emitted_2 = pres_q.get_nowait()
    assert emitted_2.asset_id == "3"


def test_manual_lock_blocks_llm_switch_and_rollback_restores_previous_outfit(tmp_path):
    sess_dir = tmp_path / "data" / "conversations" / "outfit_branch"
    store = open_session_store_for_dir(sess_dir)
    active_file = sess_dir / "active.json"
    active_file.write_text("[]", encoding="utf-8")

    char = _multi_outfit_character(tmp_path)
    cfg = _FakeConfigManager([char])

    emitted_events: list[dict] = []
    stage_updates: list[tuple[str, int]] = []
    fake_transport = SimpleNamespace(
        emit=emitted_events.append,
        stream_sink=SimpleNamespace(
            snapshot=lambda: {"sprites": [{"characterName": "Kurisu", "index": 1}]}
        ),
    )
    fake_ui = SimpleNamespace(
        update_sprite=lambda cname, idx: stage_updates.append((cname, idx))
    )

    controller = OutfitRuntimeController()
    controller.initialize(
        cfg,
        history_arg=str(active_file),
        character_names=["Kurisu"],
    )
    controller.bind_runtime(transport=fake_transport, ui_updates=fake_ui)
    persist_provider = OutfitPersistenceProvider(controller)

    store.set_outfit_state(
        OutfitState(character_name="Kurisu", active_group="校服", locked=False, updated_at_ms=100)
    )
    store.append_turn(
        turn_node_from_message(
            {"role": "user", "content": "早上好", CHAT_TURN_ID: "t1"},
            seq=1,
        )
    )
    store.append_turn(
        turn_node_from_message(
            {
                "role": "assistant",
                "content": json.dumps(
                    {"dialog": [{"character_name": "Kurisu", "sprite": "2", "speech": "早安。"}]},
                    ensure_ascii=False,
                ),
                CHAT_TURN_ID: "t1",
            },
            seq=2,
        )
    )

    store.append_turn(
        turn_node_from_message(
            {"role": "user", "content": "去换睡衣吧", CHAT_TURN_ID: "t2"},
            seq=3,
        )
    )
    switched, new_grp = controller.apply_streamed_outfit_switch(char, "睡衣")
    assert switched is True
    assert new_grp == "睡衣"
    assert store.get_outfit_state("Kurisu").active_group == "校服"

    store.append_turn(
        turn_node_from_message(
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "dialog": [
                            {
                                "character_name": "Kurisu",
                                "sprite": "4",
                                "outfit": "睡衣",
                                "speech": "换好睡衣了。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                CHAT_TURN_ID: "t2",
            },
            seq=4,
        )
    )
    persist_provider.message_added(
        MessageAddedContext(
            role="assistant",
            message={"role": "assistant", "content": "..."},
            messages=[],
        )
    )
    assert store.get_outfit_state("Kurisu").active_group == "睡衣"

    store.truncate_after(2)
    controller.resync_from_session_store()
    assert controller.active_group_for(char) == "校服"
    assert stage_updates[-1] == ("Kurisu", 1)

    controller.set_character_outfit("Kurisu", group="睡衣", locked=True)
    assert stage_updates[-1] == ("Kurisu", 3)
    blocked, stayed = controller.apply_streamed_outfit_switch(char, "校服")
    assert blocked is False
    assert stayed == "睡衣"

    close_all_session_stores()


def test_pipeline_3_perception_reflex_filters_to_active_outfit_group(tmp_path):
    char = _multi_outfit_character(tmp_path)
    active_group = ["睡衣"]
    applied: list[tuple[str, int | None, str]] = []

    coord = PerceptionCoordinator(
        get_api_config=lambda: SimpleNamespace(perception_reflex_enabled=True),
        resolve_character=lambda: char,
        resolve_active_sprite_group=lambda _c: active_group[0],
        is_chat_busy=lambda: False,
        apply_reflex=lambda cname, sprite_idx, bark: applied.append((cname, sprite_idx, bark)),
        enqueue_proactive_turn=lambda _p: False,
    )

    _name, _brief, expressions, choices, total_count = coord._character_prompt_metadata()
    assert total_count == 5
    assert set(choices.keys()).issubset({4, 5})
    for idxs in expressions.values():
        assert set(idxs).issubset({3, 4})

    coord._maybe_fire_reflex(
        ReflexDecision(act=True, sprite=1, expression="smile", bark="看到啦！"),
        character_name="Kurisu",
        expressions=expressions,
        sprite_count=total_count,
        config=PerceptionConfig(enabled=True, reflex_enabled=True),
        sprite_choices=choices,
        now_mono=100.0,
    )
    assert len(applied) == 1
    _cname, chosen_idx, _bark = applied[0]
    assert chosen_idx in {3, 4, None}
    assert chosen_idx != 1


def test_pipeline_4_transitions_and_recommendations_never_cross_outfit_groups(
    tmp_path, monkeypatch
):
    sprite_dir = tmp_path / "sprite" / "kurisu"
    sprite_dir.mkdir(parents=True)
    s_school_1 = sprite_dir / "school_1.png"
    s_school_2 = sprite_dir / "school_2.png"
    s_pajama_1 = sprite_dir / "pajama_1.png"
    for f in (s_school_1, s_school_2, s_pajama_1):
        f.write_bytes(f.name.encode())

    clip_same = sprite_dir / "same.webm"
    clip_cross = sprite_dir / "cross.webm"
    clip_same.write_bytes(b"WEBM_SAME")
    clip_cross.write_bytes(b"WEBM_CROSS")

    from core.sprite.transitions import sprite_fingerprint

    monkeypatch.setattr(
        "core.sprite.transitions.resolve_runtime_path",
        lambda p: Path(p),
    )

    p1, p2, p3 = str(s_school_1), str(s_school_2), str(s_pajama_1)
    char = Character(
        name="Kurisu",
        color="#c84b31",
        sprite_prefix="kurisu",
        sprites=[
            Sprite(path=s_school_1, group="校服"),
            Sprite(path=s_school_2, group="校服"),
            Sprite(path=s_pajama_1, group="睡衣"),
        ],
        sprite_groups=["校服", "睡衣"],
        emotion_tags="立绘 1：平静\n立绘 2：微笑\n立绘 3：困倦\n",
        sprite_transitions=[
            {
                "from_path": p1,
                "to_path": p2,
                "path": str(clip_same),
                "from_fingerprint": sprite_fingerprint(p1),
                "to_fingerprint": sprite_fingerprint(p2),
                "frame_count": TRANSITION_FRAME_COUNT,
            },
            {
                "from_path": p2,
                "to_path": p3,
                "path": str(clip_cross),
                "from_fingerprint": sprite_fingerprint(p2),
                "to_fingerprint": sprite_fingerprint(p3),
                "frame_count": TRANSITION_FRAME_COUNT,
            },
        ],
    )

    valid = list(valid_transitions(char))
    assert len(valid) == 1
    assert valid[0].path == str(clip_same)

    with pytest.raises(ValueError, match="跨服装分组"):
        transition_identity(char, p1, p3)

    monkeypatch.setattr(
        "application.characters.sprite.transition_recommendations.recent_character_dialogs",
        lambda _state, _name, limit=200: [
            [
                {"text": "第一句", "vibe": "", "assetId": "1"},
                {"text": "第二句", "vibe": "", "assetId": "2"},
                {"text": "换睡衣啦", "vibe": "", "assetId": "3"},
            ]
        ],
    )
    fake_state = SimpleNamespace(config_manager=_FakeConfigManager([char]))
    rec = analyze_transition_recommendations(fake_state, {"name": "Kurisu"})
    assert rec["items"] == [
        {
            "fromPath": p1,
            "toPath": p2,
            "count": 1,
            "probability": 1.0,
            "conditionalProbability": 1.0,
            "existing": True,
        }
    ]


def test_initial_outfit_persists_before_first_turn_and_replaces_mismatched_sprite(tmp_path):
    directory = tmp_path / "fresh"
    char = _multi_outfit_character(tmp_path)
    cfg = _FakeConfigManager([char])
    controller = OutfitRuntimeController()
    try:
        controller.initialize(
            cfg,
            history_arg=str(directory),
            auto_outfit_switch_arg=False,
            initial_outfits_raw=json.dumps({"Kurisu": "\u7761\u8863"}),
            character_names=["Kurisu"],
        )
        assert controller.resolve_initial_sprite_path(str(char.sprites[0].path)) == str(char.sprites[3].path)

        close_all_session_stores()
        reopened = open_session_store_for_dir(directory)
        assert reopened.get_outfit_state("Kurisu").active_group == "\u7761\u8863"
        assert reopened.get_auto_outfit_switch() is False
        assert not reopened.list_turns()

        controller.initialize(cfg, history_arg=str(directory), auto_outfit_switch_arg=True)
        assert reopened.get_auto_outfit_switch() is True
        assert controller.build_state_payload()["autoOutfitSwitch"] is True
    finally:
        close_all_session_stores()


@pytest.mark.parametrize(("saved_sprite", "expected_sprite"), [("2", "4"), ("5", "5")])
def test_resume_restores_the_saved_group_and_replays_a_sprite_from_it(
    tmp_path, monkeypatch, saved_sprite, expected_sprite,
):
    directory = tmp_path / "saved-chat"
    char = _multi_outfit_character(tmp_path)
    cfg = _FakeConfigManager([char])
    store = open_session_store_for_dir(directory)
    store.set_outfit_state(OutfitState("Kurisu", "睡衣", locked=True))
    store.set_auto_outfit_switch(False)
    close_session_store(directory)

    try:
        controller = OutfitRuntimeController()
        controller.initialize(cfg, history_arg=str(directory), character_names=[char.name])
        assert controller.active_group_for(char) == "睡衣"
        assert controller.is_locked(char.name)
        assert controller.auto_outfit_switch is False

        presentation_queue = queue.Queue()
        opencc = SimpleNamespace(convert=lambda value: value)
        runtime = SimpleNamespace(
            config=cfg, outfit_controller=controller, opencc=opencc,
            presentation_queue=presentation_queue,
        )
        monkeypatch.setattr(
            "application.chat.presentation.handlers.dialog_media.get_app_runtime", lambda: runtime,
        )
        dialog_queue = queue.Queue()
        assert enqueue_latest_media_replay(
            [{"role": "assistant", "content": {"dialog": [
                {"character_name": char.name, "sprite": saved_sprite, "outfit": "校服"},
                {"character_name": char.name, "speech": "still here", "sprite": "-1"},
            ]}}],
            dialog_queue=dialog_queue, opencc=opencc,
        )
        CharacterMediaHandler().handle(dialog_queue.get_nowait())

        assert presentation_queue.get_nowait().asset_id == expected_sprite
        assert store is not open_session_store_for_dir(directory)
        assert controller.active_group_for(char) == "睡衣"
    finally:
        close_session_store(directory)

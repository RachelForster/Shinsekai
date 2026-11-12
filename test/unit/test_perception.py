from __future__ import annotations

import io
import base64
from dataclasses import replace
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from tools.perception_subtitles import select_subtitles

from ai.perception.decision_client import PerceptionDecisionClient, PerceptionInferenceError
from ai.perception.prompts import (
    build_perception_messages,
    parse_perception_decision_json,
    try_extract_early_reflex,
)
from application.chat.history.state import (
    pop_last_assistant_turn_payload,
    revert_chat_history,
)
from application.chat.host.history import _serialize_history_entries_from_messages
from application.perception.coordinator import PerceptionCoordinator
from application.perception.expressions import expression_sprite_candidates
from application.perception.hooks import PerceptionAutoHooks
from application.perception.server_launcher import (
    PerceptionLocalServerManager,
    parse_local_server_endpoint,
)
from application.runtime.event_sink import (
    fold_event_into_snapshot,
    make_empty_chat_snapshot,
)
from core.perception.gatekeeper import PerceptionGatekeeper
from core.perception.models import (
    PerceptionConfig,
    PerceptionDigestResult,
    PerceptionFrame,
    RawPerceptionSnapshot,
    ReflexDecision,
    ScreenOcrScope,
)
from core.perception.raw_buffer import PerceptionRawBuffer
from core.chat_history.identity import CHAT_TURN_ID
from core.perception.cache import PERCEPTION_CONTEXT_MARKER, PROACTIVE_TURN_INSTRUCTION, RPInputCache
from plugin_system.host.service import bind_perception_runtime
from sdk.register import PluginCapabilityRegistry


class TestPerceptionRawBuffer(unittest.TestCase):
    def test_recursive_state_merge_and_drain(self) -> None:
        buf = PerceptionRawBuffer(max_events=8)
        self.assertFalse(buf.has_dirty())

        buf.ingest_state(
            {"player": {"hp": 100, "mp": 50, "debuff": "poison"}, "scene": "forest"},
            source="mod",
            game="elden_demo",
        )
        buf.ingest_state(
            {"player": {"hp": 32, "debuff": None}},
            source="mod",
            game="elden_demo",
        )

        for idx in range(10):
            buf.ingest_event(f"evt_{idx}", {"idx": idx}, source="mod", game="elden_demo")

        buf.ingest_frame(
            PerceptionFrame(
                image_base64="ZmFrZQ==",
                width=512,
                height=288,
                game="elden_demo",
            )
        )
        self.assertTrue(buf.has_dirty())

        snap = buf.drain_snapshot()
        self.assertFalse(snap.is_empty)
        self.assertEqual(snap.primary_game, "elden_demo")
        merged_state = snap.states["mod:elden_demo"]
        self.assertEqual(merged_state["player"], {"hp": 32, "mp": 50, "debuff": None})
        self.assertEqual(merged_state["scene"], "forest")
        self.assertEqual(len(snap.events), 8)
        self.assertEqual([e.event_type for e in snap.events[-3:]], ["evt_7", "evt_8", "evt_9"])
        self.assertIsNotNone(snap.frame)

        # Drain resets dirty/events/frame while keeping merged state baseline.
        self.assertFalse(buf.has_dirty())
        self.assertTrue(buf.drain_snapshot().is_empty)


class TestRPInputCacheAndGatekeeper(unittest.TestCase):
    def test_turn_context_labels_and_deduplicates_visual_and_ocr_content(self) -> None:
        cache = RPInputCache()
        cache.record_decision(PerceptionDigestResult(
            digest="镜头扫过破败的警局，下方有字幕‘就足以让我热泪盈眶’。", salience=0.85,
        ))
        cache.record_decision(PerceptionDigestResult(
            digest="右侧画面中，红色的球向右漂到了岸边，远处有灯塔。", salience=0.8,
        ))
        cache.record_decision(PerceptionDigestResult(digest="就足以让我热泪盈眶", salience=0.91))
        cache.record_screen_text(
            "就足以让我热泪盈眶！\n最不可替代的一部作品\n球向右漂到了岸边", captured_at=time.time(),
        )
        cache.record_screen_text("最不可替代的一部作品。", captured_at=time.time())
        context = cache.take_turn_context()
        self.assertIn("[画面] 镜头扫过破败的警局", context)
        self.assertIn("[字幕] 就足以让我热泪盈眶！", context)
        self.assertEqual(context.count("就足以让我热泪盈眶"), 1)
        self.assertEqual(context.count("最不可替代的一部作品"), 1)
        self.assertIn("[画面] 远处有灯塔。", context)
        self.assertEqual(context.count("球向右漂到了岸边"), 1)

    def test_expired_and_consumed_events_do_not_trigger_again(self) -> None:
        cache = RPInputCache()
        config = PerceptionConfig(enabled=True)
        gatekeeper = PerceptionGatekeeper()
        cache.record_decision(PerceptionDigestResult(digest="过期场景", salience=0.95, created_at=time.time() - 60))
        self.assertFalse(gatekeeper.evaluate(cache, config).allow)
        self.assertEqual(cache.format_for_rp_context(max_age_sec=45, include_recent_events=True), "")
        cache.record_decision(PerceptionDigestResult(digest="新场景", salience=0.85))
        self.assertTrue(gatekeeper.evaluate(cache, config).allow)
        cache.mark_consumed()
        cache.record_decision(PerceptionDigestResult(digest="新场景", salience=0.85))
        self.assertFalse(gatekeeper.evaluate(cache, config).allow)
        self.assertIn("新场景", cache.format_for_rp_context(max_age_sec=45, include_recent_events=True))

    def test_rp_input_cache_digest_and_watermark(self) -> None:
        cache = RPInputCache(max_recent_digests=3, max_notable_events=5)
        cache.record_decision(
            PerceptionDigestResult(
                digest="玩家进入迷雾森林，血量健康。",
                salience=0.42,
                player_busy=False,
                game="elden_demo",
            )
        )
        cache.record_decision(
            PerceptionDigestResult(
                reflex=ReflexDecision(act=True, sprite=1, bark="小心树精！"),
                digest="玩家遭遇树精Boss，血量骤降至20%。",
                salience=0.86,
                player_busy=False,
                game="elden_demo",
            )
        )

        self.assertTrue(cache.has_unconsumed_notable())
        ctx = cache.format_for_rp_context(consume=False)
        self.assertIn("elden_demo", ctx)
        self.assertIn("玩家遭遇树精Boss", ctx)
        self.assertIn("小心树精！", ctx)

        trigger_prompt = cache.format_proactive_trigger_prompt(consume=True)
        self.assertIn("玩家遭遇树精Boss", trigger_prompt)
        self.assertFalse(cache.has_unconsumed_notable())
        self.assertEqual(cache.unconsumed_peak_salience, 0.0)

    def test_gatekeeper_player_busy_and_critical_override(self) -> None:
        fake_now = [100.0]
        gk = PerceptionGatekeeper(monotonic_fn=lambda: fake_now[0])
        cache = RPInputCache()
        cfg = PerceptionConfig(
            enabled=True,
            proactive_enabled=True,
            salience_threshold=0.78,
            proactive_cooldown_sec=25.0,
        )

        # Busy player suppresses normal high-salience event (0.85 < 0.95).
        cache.record_decision(
            PerceptionDigestResult(
                digest="Boss二阶段激战中",
                salience=0.85,
                player_busy=True,
                game="elden_demo",
            )
        )
        verdict_busy = gk.evaluate(cache, cfg, chat_busy=False)
        self.assertFalse(verdict_busy.allow)
        self.assertEqual(verdict_busy.reason, "player_busy")

        # Critical climax event (>= 0.95) overrides player_busy.
        fake_now[0] = 101.0
        cache.record_decision(
            PerceptionDigestResult(
                digest="玩家丝血反杀Boss！",
                salience=0.96,
                player_busy=True,
                game="elden_demo",
            )
        )
        verdict_climax = gk.evaluate(cache, cfg, chat_busy=False)
        self.assertTrue(verdict_climax.allow)
        gk.notify_proactive_fired()

        # Cooldown blocks immediate re-trigger until cooldown elapses.
        fake_now[0] = 110.0
        self.assertEqual(gk.evaluate(cache, cfg, chat_busy=False).reason, "proactive_cooldown")
        fake_now[0] = 130.0
        self.assertTrue(gk.evaluate(cache, cfg, chat_busy=False).allow)


class TestPerceptionStreamingParser(unittest.TestCase):
    def test_reads_scene_fields_nested_in_reflex(self) -> None:
        parsed = parse_perception_decision_json(
            '{"reflex":{"act":false,"sprite":0,"bark":"","salience":0.0,'
            '"player_busy":false,"digest":"全黑画面，无内容"}}\n\n解析：画面为全黑。'
        )
        self.assertFalse(parsed.reflex.act)
        self.assertEqual(parsed.salience, 0)
        self.assertEqual(parsed.digest, "全黑画面，无内容")

    def test_explicit_no_reaction_without_digest_is_valid(self) -> None:
        parsed = parse_perception_decision_json(
            '{"reflex":{"act":false,"sprite":0,"bark":""},"salience":0.1,"player_busy":false,"digest":""}'
        )
        self.assertFalse(parsed.reflex.act)
        self.assertEqual(parsed.salience, 0)
        self.assertEqual(parsed.digest, "")

    def test_single_request_reflex_fields_are_independent(self) -> None:
        fields = '{"digest":"画面","salience":0.4,"player_busy":false,"reflex":%s}'
        for raw, sprite_id, bark in (
            ('{"sprite_id":null,"bark":null}', None, ""),
            ('{"sprite_id":7,"bark":null}', 7, ""),
            ('{"sprite_id":null,"bark":"好险。"}', None, "好险。"),
            ('{"sprite_id":true,"bark":null}', None, ""),
        ):
            with self.subTest(raw=raw):
                parsed = parse_perception_decision_json(fields % raw)
                self.assertEqual(parsed.reflex.sprite_id, sprite_id)
                self.assertEqual(parsed.reflex.bark, bark)
                self.assertEqual(parsed.reflex.act, bool(sprite_id or bark))
        empty = parse_perception_decision_json(
            '{"digest":"","salience":0.0,"player_busy":false,"reflex":{"sprite_id":null,"bark":null}}'
        )
        self.assertFalse(empty.reflex.act)
        null_reflex = parse_perception_decision_json(
            '{"digest":"","salience":0.0,"player_busy":false,"reflex":null}'
        )
        self.assertFalse(null_reflex.reflex.act)

    def test_screen_share_uses_viewing_context_without_game_state(self) -> None:
        snapshot = RawPerceptionSnapshot(
            states={},
            events=(),
            frame=PerceptionFrame(image_base64="ZmFrZQ=="),
            revision=1,
        )
        system, user = build_perception_messages(snapshot, previous_digest="", sprite_choices={2: "微笑", 7: "吃惊"})
        self.assertIn("和用户一起看共享屏幕", system["content"])
        self.assertIn("player_busy设为false", system["content"])
        self.assertIn("先判断当前画面与字幕的整体气氛mood", system["content"])
        self.assertIn("气氛沉重或悲伤（mood为sad或serious）时，严禁兴奋感叹", system["content"])
        self.assertIn("可以带语气词或停顿", system["content"])
        self.assertIn("结合当前画面和可读的字幕", user["content"][1]["text"])
        self.assertIn("2 微笑", system["content"])
        self.assertIn("7 吃惊", system["content"])
        self.assertIn('"reflex":{"sprite_id":null,"bark":null}', system["content"])
        self.assertNotIn('"act":true', system["content"])

    def test_zero_frame_diff_threshold_is_preserved(self) -> None:
        config = PerceptionConfig.from_api_config(SimpleNamespace(perception_diff_threshold=0))
        self.assertEqual(config.diff_threshold, 0)

    def test_shared_screen_uses_voice_style_without_sending_character_lore(self) -> None:
        snapshot = RawPerceptionSnapshot({}, (), PerceptionFrame("ZmFrZQ=="), 1)
        system, user = build_perception_messages(
            snapshot,
            previous_digest="",
            character_name="拉法尔",
            character_brief="凭借合理判断处事，后来为地动说所吸引，追寻真理。",
            voice_style="理性干脆、自信敏锐",
            recent_barks=["刚才那句很有意思。"],
        )
        self.assertIn("理性干脆、自信敏锐", system["content"])
        self.assertNotIn("拉法尔", system["content"])
        self.assertNotIn("地动说", system["content"])
        self.assertIn("刚才那句很有意思。", user["content"][1]["text"])

    def test_visual_model_can_return_a_numeric_sprite_id_as_a_string(self) -> None:
        result = parse_perception_decision_json(
            '{"digest":"看见海面","reflex":{"sprite_id":"12","bark":null}}'
        )
        self.assertTrue(result.reflex.act)
        self.assertEqual(result.reflex.sprite_id, 12)

    def test_early_reflex_extraction_before_full_json(self) -> None:
        partial_1 = '{"reflex":{"act":true,"sprite":2,'
        self.assertIsNone(try_extract_early_reflex(partial_1))

        partial_2 = '{"reflex":{"act":true,"sprite":2,"bark":"小心背后！"},"salience":0.84,"digest":"玩家正在'
        reflex = try_extract_early_reflex(partial_2)
        self.assertIsNotNone(reflex)
        assert reflex is not None
        self.assertTrue(reflex.act)
        self.assertEqual(reflex.sprite, 2)
        self.assertEqual(reflex.bark, "小心背后！")

        full_raw = (
            "```json\n"
            '{"reflex":{"act":true,"sprite":2,"bark":"小心背后！"},'
            '"salience":0.84,"player_busy":false,"digest":"玩家被偷袭"}\n'
            "```"
        )
        parsed = parse_perception_decision_json(full_raw, game="demo")
        self.assertTrue(parsed.reflex.act)
        self.assertEqual(parsed.reflex.sprite, 2)
        self.assertEqual(parsed.reflex.bark, "小心背后！")
        self.assertEqual(parsed.digest, "玩家被偷袭")
        self.assertAlmostEqual(parsed.salience, 0.84)
        self.assertEqual(parsed.game, "demo")


class TestSubtitleSelection(unittest.TestCase):
    def test_keeps_lower_center_lines_and_excludes_interface_text(self) -> None:
        def row(left, top, right, bottom, text):
            return ([(left, top), (right, top), (right, bottom), (left, bottom)], text, 0.99)

        overlays = [
            row(345, 72, 935, 127, "热门科普标题"),
            row(1030, 545, 1210, 584, "频道水印"),
            row(37, 644, 127, 672, "03:48"),
            row(535, 659, 745, 680, "倍速"),
        ]
        captions = [
            row(360, 553, 920, 583, "海水升温后蒸发更快"),
            row(410, 592, 870, 624, "水汽遇冷凝结成水滴"),
        ]
        self.assertEqual(
            select_subtitles([*overlays, *reversed(captions)], width=1280, height=720),
            "海水升温后蒸发更快\n水汽遇冷凝结成水滴",
        )
        self.assertEqual(select_subtitles(overlays, width=1280, height=720), "")


class TestPerceptionDecisionClient(unittest.TestCase):
    def test_ocr_request_passes_the_selected_region(self) -> None:
        selection = {"mode": "region", "region": {"x": 0.1, "y": 0.7, "width": 0.8, "height": 0.2}}
        frame = PerceptionFrame("YQ==", ocr_scope=ScreenOcrScope.from_payload(selection))
        response = io.BytesIO(json.dumps({"shinsekai_perception": {"ocrText": "范围内"}}).encode())
        client = PerceptionDecisionClient()
        with patch.object(client, "_open", return_value=response) as open_request:
            self.assertEqual(client.read_screen_text(frame, PerceptionConfig(ocr_enabled=True)), "范围内")
        self.assertEqual(json.loads(open_request.call_args.args[0].data)["ocrScope"], selection)
        with self.assertRaises(ValueError):
            ScreenOcrScope.from_payload({"mode": "region", "region": {**selection["region"], "width": 2}})

    def test_repeated_screen_frame_does_not_repeat_the_previous_collage_description(self) -> None:
        client = PerceptionDecisionClient()
        image = io.BytesIO()
        Image.new("RGB", (512, 288), "white").save(image, format="PNG")
        frame = PerceptionFrame(
            base64.b64encode(image.getvalue()).decode(), mime_type="image/png", width=512, height=288,
        )
        content = json.dumps({"digest": "雪山。", "reflex": {"sprite_id": 2, "bark": "雪山！"}})
        for changed in (False, True):
            with self.subTest(changed=changed):
                response = io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
                response.headers = {"Content-Type": "application/json"}
                with patch.object(client, "_open", return_value=response) as open_request:
                    result = client.decide(
                        RawPerceptionSnapshot({}, (), frame, 2), PerceptionConfig(),
                        previous_frame=frame, previous_digest="左侧是海滩，右侧是雪山。",
                        screen_text="积雪反射更多阳光" if changed else "", screen_text_changed=changed,
                    )
                text = json.loads(open_request.call_args.args[0].data)["messages"][-1]["content"][-1]["text"]
                if changed:
                    self.assertIn("积雪反射更多阳光", text)
                else:
                    self.assertNotIn("海滩", text)
                self.assertEqual(result.digest, "雪山。")
                self.assertEqual(result.reflex.act, changed)

    def test_combines_earlier_and_current_frames_in_one_request(self) -> None:
        def make_frame(color: str) -> PerceptionFrame:
            image = io.BytesIO()
            Image.new("RGB", (900, 500), color).save(image, format="PNG")
            return PerceptionFrame(base64.b64encode(image.getvalue()).decode(), mime_type="image/png")

        client = PerceptionDecisionClient()
        content = json.dumps({"digest": "画面变蓝。", "salience": 0.4, "reflex": None})
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
        response.headers = {"Content-Type": "application/json"}
        snapshot = RawPerceptionSnapshot({}, (), make_frame("blue"), 2)
        with patch.object(client, "_open", return_value=response) as open_request:
            client.decide(
                snapshot, PerceptionConfig(ocr_enabled=True), previous_frame=make_frame("red"),
                screen_text="太阳通过辐射给地球传热", previous_screen_text="太空几乎是真空",
                screen_text_changed=True, retry_unreadable=False,
            )
        open_request.assert_called_once()
        request = open_request.call_args.args[0]
        self.assertIsNone(request.get_header("X-shinsekai-ocr-frame-max-side"))
        image_item, text_item = json.loads(request.data)["messages"][-1]["content"]
        self.assertIn("右侧为当前画面", text_item["text"])
        self.assertIn("当前字幕或屏幕文字", text_item["text"])
        self.assertLess(text_item["text"].index("太空几乎是真空"), text_item["text"].index("太阳通过辐射给地球传热"))
        image_bytes = base64.b64decode(image_item["image_url"]["url"].split(",", 1)[1])
        with Image.open(io.BytesIO(image_bytes)) as collage:
            self.assertGreater(collage.width, 512)
            self.assertGreater(collage.getpixel((100, 100))[0], 200)
            self.assertGreater(collage.getpixel((collage.width - 100, 100))[2], 200)

    def test_retains_ocr_when_live_model_produces_no_digest(self) -> None:
        client = PerceptionDecisionClient()
        metadata = {"shinsekai_perception": {"ocrText": "去城门看看"}}
        stream = io.BytesIO(f"data: {json.dumps(metadata)}\n\ndata: [DONE]\n\n".encode())
        stream.headers = {"Content-Type": "text/event-stream"}
        snapshot = RawPerceptionSnapshot({}, (), PerceptionFrame("ZmFrZQ=="), 1)

        with patch.object(client, "_open", return_value=stream) as open_request:
            result = client.decide(snapshot, PerceptionConfig(ocr_enabled=True), retry_unreadable=False)

        self.assertEqual(result.ocr_text, "去城门看看")
        self.assertEqual(open_request.call_args.args[0].get_header("X-shinsekai-ocr-frame-max-side"), "512")
        cache = RPInputCache()
        cache.record_decision(result)
        cache.record_decision(result)
        context = cache.format_for_rp_context(include_recent_events=True)
        self.assertEqual(context.count("去城门看看"), 1)
        self.assertEqual(cache.format_for_rp_context(include_recent_events=False), "")

    def test_retries_unreadable_stream_once_as_json(self) -> None:
        client = PerceptionDecisionClient()
        stream = io.BytesIO(b"data: [DONE]\n\n")
        stream.headers = {"Content-Type": "text/event-stream"}
        content = json.dumps({"reflex": {"act": False}, "digest": "A yellow umbrella."})
        completed = io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
        completed.headers = {"Content-Type": "application/json"}
        snapshot = RawPerceptionSnapshot({}, (), PerceptionFrame("ZmFrZQ=="), 1)

        with patch.object(client, "_open", side_effect=[stream, completed]) as open_request:
            result = client.decide(snapshot, PerceptionConfig())

        self.assertEqual(result.digest, "A yellow umbrella.")
        self.assertEqual(
            [json.loads(call.args[0].data)["stream"] for call in open_request.call_args_list],
            [True, False],
        )

    def test_reports_model_error_event_without_retrying(self) -> None:
        client = PerceptionDecisionClient()
        stream = io.BytesIO(b'data: {"error":{"message":"CUDA out of memory"}}\n\n')
        stream.headers = {"Content-Type": "text/event-stream"}
        snapshot = RawPerceptionSnapshot({}, (), PerceptionFrame("ZmFrZQ=="), 1)

        with patch.object(client, "_open", return_value=stream) as open_request:
            with self.assertRaisesRegex(PerceptionInferenceError, "CUDA out of memory"):
                client.decide(snapshot, PerceptionConfig())
            open_request.assert_called_once()


class TestPerceptionHooksAndCoordinator(unittest.TestCase):
    def test_screen_audio_defers_normal_replies_but_allows_a_pause_or_urgent_scene(self) -> None:
        clock = [100.0]
        queued = []
        coordinator = PerceptionCoordinator(
            get_api_config=lambda: SimpleNamespace(perception_proactive_cooldown_sec=3.0),
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda *_args: None,
            enqueue_proactive_turn=lambda prompt: queued.append(prompt) or True,
            gatekeeper=PerceptionGatekeeper(monotonic_fn=lambda: clock[0]),
        )
        cache = coordinator.rp_input_cache
        hooks = PerceptionAutoHooks(
            rp_input_cache=cache,
            gatekeeper=coordinator.gatekeeper,
            proactive_threshold=coordinator.proactive_turn_threshold,
        )

        def report(audio):
            coordinator.ingest({"screenShareActive": True, "source": "screen_share", "screenPlaybackAudio": audio})

        def scene(digest, salience):
            cache.record_decision(PerceptionDigestResult(digest=digest, salience=salience))
            coordinator._maybe_trigger_proactive(coordinator.current_config())

        report("playing")
        scene("镜头转向窗外", 0.85)
        self.assertEqual(queued, [])
        report("quiet")
        self.assertEqual(len(queued), 1)
        report("playing")
        self.assertFalse(hooks.prepare_turn("audio-resumed", "perception"))

        scene("路人即将被倒下的树砸中", 0.98)
        self.assertEqual(len(queued), 2)
        self.assertTrue(hooks.prepare_turn("urgent", "perception"))
        coordinator.mark_proactive_turn_admitted()

        clock[0] += 4.0
        cache.record_screen_text("今晚的节目到这里", captured_at=time.time())
        report("quiet")
        self.assertEqual(len(queued), 2)
        report("stopped")
        self.assertEqual(len(queued), 3)
        self.assertTrue(hooks.prepare_turn("paused", "perception"))
        coordinator.mark_proactive_turn_admitted()

        clock[0] += 4.0
        cache.record_screen_text("片尾字幕", captured_at=time.time())
        report("stopped")
        self.assertEqual(len(queued), 3)

    def test_changing_ocr_scope_discards_pending_results_and_buffered_subtitles(self) -> None:
        old_ocr_started = threading.Event()
        release_old_ocr = threading.Event()
        new_text_buffered = threading.Event()

        class RecordingCache(RPInputCache):
            def record_screen_text(self, text, *, captured_at):
                super().record_screen_text(text, captured_at=captured_at)
                if text == "新范围内的字幕":
                    new_text_buffered.set()

        def read_screen_text(frame, _config):
            if frame.ocr_scope.mode == "full":
                old_ocr_started.set()
                release_old_ocr.wait(timeout=3.0)
                return "旧范围内的新字幕"
            return "新范围内的字幕"

        cache = RecordingCache()
        coordinator = PerceptionCoordinator(
            get_api_config=lambda: SimpleNamespace(perception_ocr_enabled=True),
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda *_args: None,
            enqueue_proactive_turn=lambda _prompt: False,
            rp_input_cache=cache,
            decision_client=SimpleNamespace(
                read_screen_text=read_screen_text,
                decide=lambda *_args, **_kwargs: PerceptionDigestResult(),
            ),
        )
        frame = {"source": "screen_share", "imageBase64": "YQ==", "ocrOnly": True}
        coordinator.start()
        try:
            coordinator.ingest({**frame, "ocrScope": {"mode": "full"}})
            self.assertTrue(old_ocr_started.wait(timeout=1.5))
            cache.record_screen_text("旧范围内已缓存的字幕", captured_at=time.time())
            coordinator.ingest({**frame, "ocrScope": {"mode": "bottom"}})
            self.assertEqual(cache.recent_subtitles(), [])
            release_old_ocr.set()
            self.assertTrue(new_text_buffered.wait(timeout=1.5))
            self.assertEqual(cache.recent_subtitles(), ["新范围内的字幕"])
        finally:
            release_old_ocr.set()
            coordinator.stop()

    def test_ocr_only_frames_reach_chat_and_new_subtitles_wake_vision(self) -> None:
        vision_started = threading.Event()
        release_vision = threading.Event()
        initial_ocr_started = threading.Event()
        text_buffered = threading.Event()
        read_images = []
        analyzed = []

        class RecordingCache(RPInputCache):
            def record_screen_text(self, text, *, captured_at):
                super().record_screen_text(text, captured_at=captured_at)
                if text:
                    text_buffered.set()

        class FakeDecisionClient:
            def decide(self, snapshot, _config, **kwargs):
                analyzed.append((
                    snapshot.frame.image_base64, kwargs["previous_screen_text"],
                    kwargs["screen_text"], kwargs["screen_text_changed"],
                ))
                vision_started.set()
                release_vision.wait(timeout=3.0)
                return PerceptionDigestResult(digest="门前站着一个人。")

            def read_screen_text(self, frame, _config):
                read_images.append(frame.image_base64)
                initial_ocr_started.set()
                return {
                    "Yw==": "太空几乎是真空。",
                    "ZA==": "太空几乎是真空！",
                    "ZQ==": "辐射仍然能传播热量。",
                }.get(frame.image_base64, "")

        coordinator = PerceptionCoordinator(
            get_api_config=lambda: SimpleNamespace(
                perception_ocr_enabled=True, perception_ocr_interval_sec=0.5, perception_interval_sec=0.5,
            ),
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda *_args: None,
            enqueue_proactive_turn=lambda _prompt: False,
            rp_input_cache=RecordingCache(),
            decision_client=FakeDecisionClient(),
        )
        coordinator.start()
        try:
            coordinator.ingest({"source": "screen_share", "imageBase64": "YQ=="})
            self.assertTrue(vision_started.wait(timeout=1.5))
            self.assertTrue(initial_ocr_started.wait(timeout=1.5))
            coordinator.ingest({"source": "screen_share", "imageBase64": "Yg==", "ocrOnly": True})
            coordinator.ingest({"source": "screen_share", "imageBase64": "Yw==", "ocrOnly": True})
            self.assertTrue(text_buffered.wait(timeout=1.5))
            self.assertEqual(read_images, ["YQ==", "Yw=="])
            self.assertTrue(coordinator.raw_buffer.has_dirty())
            self.assertIn("太空几乎是真空", coordinator.rp_input_cache.take_turn_context())
            self.assertEqual(coordinator.rp_input_cache.take_turn_context(), "")
            release_vision.set()
            coordinator.wait_for_buffered_context()
            self.assertEqual(analyzed, [
                ("YQ==", "", "", False),
                ("Yw==", "", "太空几乎是真空。", True),
            ])
            self.assertIn("门前站着一个人", coordinator.rp_input_cache.take_turn_context())

            text_buffered.clear()
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZA==", "ocrOnly": True})
            self.assertTrue(text_buffered.wait(timeout=1.5))
            self.assertFalse(coordinator.raw_buffer.has_dirty())

            text_buffered.clear()
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZQ==", "ocrOnly": True})
            self.assertTrue(text_buffered.wait(timeout=1.5))
            coordinator.wait_for_buffered_context()
            self.assertEqual(analyzed[-1], ("ZQ==", "太空几乎是真空！", "辐射仍然能传播热量。", True))
        finally:
            release_vision.set()
            coordinator.stop()

    def test_turn_handoff_reuses_its_snapshot_and_leaves_later_observations_pending(self) -> None:
        cache = RPInputCache()
        hooks = PerceptionAutoHooks(rp_input_cache=cache, gatekeeper=PerceptionGatekeeper())
        cache.record_decision(PerceptionDigestResult(digest="角色打开了门。", salience=0.92))
        cache.record_screen_text("进入走廊", captured_at=time.time())
        self.assertTrue(hooks.prepare_turn("manual", "user"))

        def make_user(turn_id, source, content):
            user = {"role": "user", CHAT_TURN_ID: turn_id, "source": source, "content": content}
            hooks.before_chat(SimpleNamespace(messages=[user]))
            return user["content"]

        with self.assertLogs("application.perception.hooks", level="INFO") as captured:
            first = make_user("manual", "user", "门开了吗？")
        self.assertIn("角色打开了门", first)
        self.assertIn("进入走廊", first)
        self.assertTrue(first.endswith("\n\n请根据你看到的内容回复。"))
        record, = captured.records
        self.assertEqual(record.event, "perception.context.submitted")
        self.assertEqual(record.source, "user")
        self.assertEqual(record.history_turn_id, "manual")
        self.assertEqual(record.getMessage().partition("\n")[2], first.partition("\n\n")[2])
        self.assertFalse(hooks.prepare_turn("stale", "perception"))

        cache.record_decision(PerceptionDigestResult(digest="远处亮起火光。", salience=0.95))
        cache.record_screen_text("着火了", captured_at=time.time())
        self.assertTrue(hooks.prepare_turn("auto", "perception"))
        with self.assertLogs("application.perception.hooks", level="INFO") as captured:
            proactive = make_user("auto", "perception", PROACTIVE_TURN_INSTRUCTION)
        self.assertTrue(proactive.endswith("\n\n请根据你看到的内容回复。"))
        record, = captured.records
        self.assertEqual(record.source, "perception")
        self.assertEqual(record.history_turn_id, "auto")
        self.assertEqual(record.getMessage().partition("\n")[2], proactive.partition("\n\n")[2])
        self.assertIn("远处亮起火光", proactive)
        self.assertIn("着火了", proactive)
        self.assertNotIn("进入走廊", proactive)
        cache.record_screen_text("警告", captured_at=time.time())
        self.assertEqual(make_user("auto", "perception", PROACTIVE_TURN_INSTRUCTION), proactive)
        self.assertIn("警告", cache.take_turn_context())

    def test_rotates_matching_sprites_and_tracks_recent_spoken_barks(self) -> None:
        choices = expression_sprite_candidates(
            [{"path": "idle.png"}, {"path": "gasp.png"}, {"path": "surprise.png"}, {"path": "gasp.png"}],
            "立绘 1：平静\n立绘 2：惊讶\n立绘 3：吃惊\n立绘 4：惊喜",
        )
        self.assertEqual(choices["平静"], (0,))
        self.assertEqual(choices["惊讶"], (1, 2))
        shown: list[tuple[int | None, str]] = []
        coordinator = PerceptionCoordinator(
            get_api_config=lambda: None,
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda _name, sprite, bark: shown.append((sprite, bark)),
            enqueue_proactive_turn=lambda _prompt: False,
        )
        with patch("application.perception.coordinator.time.monotonic", side_effect=[100, 102, 106]):
            for bark in ("这也太夸张了吧！", "那个人是谁？", "等等，门后好像有人。"):
                coordinator._maybe_fire_reflex(
                    ReflexDecision(act=True, expression="惊喜", bark=bark),
                    character_name="Nanami",
                    expressions=choices,
                    sprite_count=4,
                    config=PerceptionConfig(reflex_cooldown_sec=3.5),
                )
        self.assertEqual(shown, [(1, "这也太夸张了吧！"), (2, ""), (1, "等等，门后好像有人。")])
        self.assertEqual(
            coordinator._reflex_policy.recent_spoken_barks("Nanami", now=110.0),
            ["这也太夸张了吧！", "等等，门后好像有人。"],
        )

    def test_filters_recent_bubbles_after_a_different_reaction(self) -> None:
        shown: list[str] = []
        coordinator = PerceptionCoordinator(
            get_api_config=lambda: None,
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda _name, _sprite, bark: shown.append(bark),
            enqueue_proactive_turn=lambda _prompt: False,
        )
        with patch("application.perception.coordinator.time.monotonic", side_effect=[100, 104, 108, 112, 150]):
            for bark in ("这也太厉害了吧！", "等等，他要去哪？", "哇，这也太厉害了！", "这也太厉害了吧。", "这也太厉害了吧！"):
                coordinator._maybe_fire_reflex(
                    ReflexDecision(act=True, bark=bark),
                    character_name="Nanami",
                    expressions={},
                    sprite_count=0,
                    config=PerceptionConfig(reflex_cooldown_sec=3.5),
                )
        self.assertEqual(shown, ["这也太厉害了吧！", "等等，他要去哪？", "这也太厉害了吧！"])

    def test_default_bubble_cooldown_leaves_explicit_sprite_switches_independent(self) -> None:
        from config.schema import ApiConfig

        config = PerceptionConfig()
        self.assertEqual(config.reflex_cooldown_sec, 15.0)
        self.assertEqual(PerceptionConfig.from_api_config(ApiConfig()).reflex_cooldown_sec, 15.0)
        self.assertEqual(
            PerceptionConfig.from_api_config(SimpleNamespace(perception_reflex_cooldown_sec=7)).reflex_cooldown_sec,
            7.0,
        )
        shown = []
        coordinator = PerceptionCoordinator(
            get_api_config=lambda: None,
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda _name, sprite, bark: shown.append((sprite, bark)),
            enqueue_proactive_turn=lambda _prompt: False,
        )
        decisions = (
            ReflexDecision(act=True, bark="它怎么浮起来了？"),
            ReflexDecision(act=True, sprite_id=1, bark="气球飘远了。"),
            ReflexDecision(act=True, bark="看起来很轻。"),
            ReflexDecision(act=True, bark="这片海真美。"),
        )
        with patch("application.perception.coordinator.time.monotonic", side_effect=[100, 105, 114.99, 115]):
            for decision in decisions:
                coordinator._maybe_fire_reflex(
                    decision, character_name="拉法尔", config=config, sprite_count=3,
                    expressions={"平静": (0,), "好奇": (1,), "开心": (2,)},
                    sprite_choices={1: "平静", 2: "沉思", 3: "微笑"},
                )
        self.assertEqual(shown, [(None, "它怎么浮起来了？"), (0, ""), (None, "这片海真美。")])

    def test_auto_hooks_injects_context_and_marks_consumed(self) -> None:
        cache = RPInputCache()
        gk = PerceptionGatekeeper()
        cache.record_decision(
            PerceptionDigestResult(
                digest="玩家刚打开背包查看药水。",
                salience=0.65,
                game="rpg",
            )
        )
        hooks = PerceptionAutoHooks(
            rp_input_cache=cache,
            gatekeeper=gk,
            is_enabled=lambda: True,
        )
        old_turn = {"role": "user", "source": "perception", "content": PERCEPTION_CONTEXT_MARKER + "旧画面"}
        user = {"role": "user", "content": [{"type": "text", "text": "你看我包里有什么"}]}
        ctx = SimpleNamespace(messages=[old_turn, {"role": "assistant", "content": "看到了。"}, user])
        hooks.before_chat(ctx)  # type: ignore[arg-type]
        hooks.before_chat(ctx)  # type: ignore[arg-type]

        self.assertEqual(len(ctx.messages), 3)
        self.assertNotIn("旧画面", old_turn["content"])
        self.assertEqual(len(user["content"]), 2)
        self.assertEqual(user["content"][0]["text"], "你看我包里有什么")
        self.assertIn("玩家刚打开背包查看药水", user["content"][1]["text"])
        self.assertFalse(cache.has_unconsumed_notable())

    def test_live_frames_replace_old_scenes_and_select_tagged_sprites(self) -> None:
        analyzed: list[tuple[str, str]] = []
        reactions: list[tuple[str, int | None, str]] = []

        class FakeDecisionClient:
            def decide(self, snapshot, config, **kwargs):
                image = snapshot.frame.image_base64
                analyzed.append((image, kwargs["previous_digest"]))
                digest, sprite_id, bark = {
                    "YQ==": ("蓝色的大海和沙滩，岸边有棕榈树。", 2, "蓝色的大海……"),
                    "Yg==": ("门打开", 3, "咦，门怎么开了？"),
                    "Yw==": ("门打开", 3, "咦，门怎么开了？"),
                    "ZA==": ("门打开", 2, ""),
                    "ZQ==": ("", 3, ""),
                }[image]
                reflex = ReflexDecision(act=True, sprite_id=sprite_id, bark=bark)
                return PerceptionDigestResult(reflex=reflex, digest=digest)

        coordinator = PerceptionCoordinator(
            get_api_config=lambda: SimpleNamespace(perception_interval_sec=0.5, perception_reflex_cooldown_sec=3.5),
            resolve_character=lambda: SimpleNamespace(
                name="Nanami",
                sprites=[{"path": "idle.png"}, {"path": "a.png"}, {"path": "b.png"}],
                emotion_tags="立绘 1：平静\n立绘 2：微笑\n立绘 3：惊讶",
            ),
            is_chat_busy=lambda: False,
            apply_reflex=lambda name, sprite, bark: reactions.append((name, sprite, bark)),
            enqueue_proactive_turn=lambda _prompt: False,
            decision_client=FakeDecisionClient(),  # type: ignore[arg-type]
        )
        coordinator.start()
        try:
            coordinator.ingest({
                "source": "screen_share", "screenShareActive": True,
                "imageBase64": "b2xk", "capturedAtMs": (time.time() - 30) * 1000,
            })
            coordinator.wait_for_buffered_context()
            self.assertEqual(analyzed, [])
            coordinator.ingest({"source": "screen_share", "imageBase64": "YQ=="})
            coordinator.wait_for_buffered_context()
            coordinator.ingest({"source": "screen_share", "imageBase64": "Yg=="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(analyzed, [("YQ==", ""), ("Yg==", "蓝色的大海和沙滩，岸边有棕榈树。")])
            self.assertEqual([sprite for _name, sprite, _bark in reactions], [1, 2])
            self.assertEqual(reactions[0][2], "蓝色的大海……")
            self.assertEqual(reactions[-1][2], "")
            coordinator.ingest({"source": "screen_share", "imageBase64": "Yw=="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(len(reactions), 2)

            coordinator.ingest({"source": "screen_share", "imageBase64": "ZA=="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(reactions[-1], ("Nanami", 1, ""))
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZQ=="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(reactions[-1], ("Nanami", 2, ""))
            self.assertEqual(coordinator.rp_input_cache.current_digest, "门打开")
        finally:
            coordinator.stop()

    def test_unlisted_sprite_id_does_not_block_valid_bark(self) -> None:
        shown = []
        coordinator = PerceptionCoordinator(
            get_api_config=lambda: None,
            resolve_character=lambda: None,
            is_chat_busy=lambda: False,
            apply_reflex=lambda _name, sprite, bark: shown.append((sprite, bark)),
            enqueue_proactive_turn=lambda _prompt: False,
        )
        coordinator._maybe_fire_reflex(
            ReflexDecision(act=True, sprite_id=2, bark="留神门口。"),
            character_name="Nanami",
            expressions={},
            sprite_count=3,
            sprite_choices={1: "平静", 3: "严肃"},
            config=PerceptionConfig(),
        )
        self.assertEqual(shown, [(None, "留神门口。")])

    def test_coordinator_end_to_end_fast_reflex_and_proactive_gate(self) -> None:
        reflex_events: list[tuple[str, int | None, str]] = []
        proactive_prompts: list[str] = []
        done_event = threading.Event()

        class FakeDecisionClient:
            def decide(self, snapshot, config, **kwargs):
                on_early = kwargs.get("on_early_reflex")
                reflex = ReflexDecision(act=True, sprite=1, bark="哇，干得漂亮！")
                if on_early:
                    on_early(reflex)
                return PerceptionDigestResult(
                    reflex=reflex,
                    digest="玩家成功击败强敌精英怪。",
                    salience=0.91,
                    player_busy=False,
                    game=snapshot.primary_game,
                )

        api_cfg = SimpleNamespace(
            perception_enabled=True,
            perception_base_url="http://127.0.0.1:8091/v1",
            perception_api_key="EMPTY",
            perception_model="Qwen/Qwen3-VL-2B-Instruct",
            perception_interval_sec=0.5,
            perception_frame_max_side=512,
            perception_diff_threshold=0.03,
            perception_reflex_enabled=True,
            perception_reflex_cooldown_sec=1.0,
            perception_proactive_enabled=True,
            perception_salience_threshold=0.78,
            perception_proactive_cooldown_sec=10.0,
        )
        character = SimpleNamespace(
            name="Nanami",
            character_brief="活泼可靠的同伴",
            sprites=[SimpleNamespace(path="a.png"), SimpleNamespace(path="b.png")],
            emotion_tags="立绘 0：微笑\n立绘 1：惊喜\n",
        )

        def on_proactive(prompt: str) -> bool:
            proactive_prompts.append(prompt)
            done_event.set()
            return True

        coordinator = PerceptionCoordinator(
            get_api_config=lambda: api_cfg,
            resolve_character=lambda: character,
            is_chat_busy=lambda: False,
            apply_reflex=lambda name, sprite, bark: reflex_events.append((name, sprite, bark)),
            enqueue_proactive_turn=on_proactive,
            decision_client=FakeDecisionClient(),  # type: ignore[arg-type]
        )
        coordinator.start()
        try:
            coordinator.ingest({"source": "plugin:demo", "game": "demo", "event": "boss_defeated"})
            self.assertTrue(done_event.wait(timeout=3.0))
            self.assertEqual(reflex_events, [("Nanami", 1, "哇，干得漂亮！")])
            self.assertEqual(len(proactive_prompts), 1)
            self.assertEqual(proactive_prompts, [PROACTIVE_TURN_INSTRUCTION])
            self.assertTrue(coordinator.rp_input_cache.has_unconsumed_notable())
            hooks = PerceptionAutoHooks(
                rp_input_cache=coordinator.rp_input_cache,
                gatekeeper=coordinator.gatekeeper,
                proactive_threshold=coordinator.proactive_turn_threshold,
            )
            self.assertTrue(hooks.prepare_turn("auto", "perception"))
            user = {"role": "user", "source": "perception", CHAT_TURN_ID: "auto", "content": proactive_prompts[0]}
            hooks.before_chat(SimpleNamespace(messages=[user]))
            self.assertIn("玩家成功击败强敌精英怪", user["content"])
            self.assertFalse(coordinator.rp_input_cache.has_unconsumed_notable())
        finally:
            coordinator.stop(timeout=2.0)

    def test_plugin_sdk_perception_binding(self) -> None:
        captured: list[dict] = []
        bind_perception_runtime(lambda payload: captured.append(dict(payload)) or True)
        try:
            registry = PluginCapabilityRegistry()
            ctrl = registry.perception("game_bridge")
            self.assertTrue(ctrl.push_state({"hp": 88}, game="hollow"))
            self.assertTrue(ctrl.push_event("heal", {"amount": 20}, game="hollow"))
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[0]["source"], "plugin:game_bridge")
            self.assertEqual(captured[0]["state"], {"hp": 88})
            self.assertEqual(captured[1]["events"][0]["type"], "heal")
        finally:
            bind_perception_runtime(None)


class TestPerceptionHistoryAndSnapshotInvariants(unittest.TestCase):
    def test_history_serialization_and_revert_ignore_perception_user_prompts(self) -> None:
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "[Nanami]<1>[你好呀！]"},
            {
                "role": "user",
                "source": "perception",
                "content": "[系统感知触发：玩家击败Boss]",
            },
            {"role": "assistant", "content": "[Nanami]<2>[太厉害了吧！]"},
            {"role": "user", "content": "接下来去哪？"},
            {"role": "assistant", "content": "[Nanami]<1>[去北边看看吧。]"},
        ]

        entries = _serialize_history_entries_from_messages(messages, user_display_name="你")
        user_entries = [e for e in entries if e["role"] == "user"]
        self.assertEqual([e["text"] for e in user_entries], ["你: 你好", "你: 接下来去哪？"])
        self.assertEqual([e["revertUserIndex"] for e in user_entries], [0, 1])

        # Popping last assistant turn removes the real user turn ("接下来去哪？") cleanly.
        msg_copy_1 = [dict(m) for m in messages]
        chat_history = [
            "<b>你</b>：你好",
            "<b>Nanami</b>：你好呀！",
            "<b>Nanami</b>：太厉害了吧！",
            "<b>你</b>：接下来去哪？",
            "<b>Nanami</b>：去北边看看吧。",
        ]
        popped = pop_last_assistant_turn_payload(chat_history, msg_copy_1)
        self.assertEqual(popped["text"], "接下来去哪？")
        # Even if another pop happens after a proactive perception turn, it pops back to "你好" cleanly.
        popped_prev = pop_last_assistant_turn_payload(chat_history, msg_copy_1)
        self.assertEqual(popped_prev["text"], "你好")

        # Reverting to user_index=1 on original history targets "接下来去哪？", not perception prompt!
        class _FakeLLM:
            def __init__(self, initial: list[dict]) -> None:
                self.messages = [dict(m) for m in initial]

            def get_messages(self) -> list[dict]:
                return list(self.messages)

            def set_messages(self, updated: list[dict]) -> None:
                self.messages = list(updated)

        replayed: list[str] = []
        fake_window = SimpleNamespace(
            setDisplayWords=lambda text: replayed.append(text),
            setOptions=lambda opts: None,
        )
        llm_manager_2 = _FakeLLM(messages)
        chat_history_2 = [
            "<b>你</b>：你好",
            "<b>Nanami</b>：你好呀！",
            "<b>Nanami</b>：太厉害了吧！",
            "<b>你</b>：接下来去哪？",
            "<b>Nanami</b>：去北边看看吧。",
        ]
        revert_chat_history(1, llm_manager_2, chat_history_2, fake_window)
        # Proactive turn before user_index=1 remains intact and is replayed on stage.
        self.assertEqual(len(llm_manager_2.messages), 5)
        self.assertEqual(
            chat_history_2,
            ["<b>你</b>：你好", "<b>Nanami</b>：你好呀！", "<b>Nanami</b>：太厉害了吧！"],
        )
        self.assertEqual(replayed, ["<b>Nanami</b>：太厉害了吧！"])

    def test_snapshot_folding_for_perception_and_sprite_reaction(self) -> None:
        snap = make_empty_chat_snapshot()
        now_ms = int(time.time() * 1000)
        snap = fold_event_into_snapshot(
            snap,
            {
                "type": "perception.state",
                "seq": 1,
                "ts": now_ms,
                "perception": {"enabled": True, "active": True, "screenShareActive": True},
            },
        )
        self.assertTrue(snap["perception"]["screenShareActive"])

        snap = fold_event_into_snapshot(
            snap,
            {
                "type": "sprite.reaction",
                "seq": 2,
                "ts": now_ms,
                "characterName": "Nanami",
                "text": "唔……好险！",
                "durationMs": 3200,
            },
        )
        self.assertEqual(snap["spriteReaction"]["text"], "唔……好险！")
        self.assertEqual(snap["spriteReaction"]["expiresAt"], now_ms + 3200)

        snap = fold_event_into_snapshot(
            snap,
            {"type": "session.closed", "seq": 3, "ts": now_ms + 100, "reason": "closed"},
        )
        self.assertIsNone(snap["perception"])
        self.assertIsNone(snap["spriteReaction"])


class TestPerceptionLocalServerLauncher(unittest.TestCase):
    def test_endpoint_validation_and_managed_start_stop(self) -> None:
        self.assertEqual(
            parse_local_server_endpoint("http://127.0.0.1:8091/v1"),
            ("127.0.0.1", 8091),
        )
        with self.assertRaises(ValueError):
            parse_local_server_endpoint("https://api.openai.com/v1")

        probe_ok = [False]
        spawned_cmds: list[list[str]] = []
        processes = []

        class _FakeProc:
            pid = 9527
            stdout = iter(["[perception-server] Ready in 2.1s | VRAM: 4135.2 MB\n"])

            def __init__(self) -> None:
                self._rc: int | None = None
                self.stdin = io.BytesIO()

            def poll(self) -> int | None:
                return self._rc

            def terminate(self) -> None:
                self._rc = 0

            def wait(self, timeout: float | None = None) -> int:
                self._rc = 0
                return 0

            def kill(self) -> None:
                self._rc = -9

        def fake_popen(cmd, **kwargs):
            spawned_cmds.append(list(cmd))
            probe_ok[0] = True
            process = _FakeProc()
            processes.append(process)
            return process

        import sys

        mgr = PerceptionLocalServerManager(
            probe_fn=lambda _cfg: {"ok": probe_ok[0], "models": ["Qwen/Qwen3-VL-2B-Instruct"]},
            popen_fn=fake_popen,  # type: ignore[arg-type]
        )
        started = mgr.start(
            base_url="http://127.0.0.1:8091/v1",
            model="Qwen/Qwen3-VL-2B-Instruct",
            python_path=sys.executable,
        )
        self.assertTrue(started["managed"])
        self.assertEqual(started["pid"], 9527)
        self.assertEqual(spawned_cmds[0][0], sys.executable)
        self.assertIn("--stop-on-stdin-eof", spawned_cmds[0])

        # Wait briefly for readiness thread to flip starting -> running
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and mgr.status(explicit_python_path=sys.executable)["state"] == "starting":
            time.sleep(0.05)

        running = mgr.status(explicit_python_path=sys.executable)
        self.assertEqual(running["state"], "running")
        self.assertTrue(running["running"])

        stopped = mgr.stop()
        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(stopped["running"])
        self.assertTrue(processes[0].stdin.closed)

        # Verify default probe_fn signature integration with PerceptionDecisionClient.probe_health
        default_mgr = PerceptionLocalServerManager()
        default_probe_res = default_mgr._probe_fn(PerceptionConfig(base_url="http://127.0.0.1:1/v1"))
        self.assertFalse(default_probe_res["ok"])

    def test_chat_session_perception_imports_and_hook_registration(self) -> None:
        from application.perception import PerceptionCoordinator, install_perception_hooks
        from plugin_system.host import bind_perception_runtime as host_bind_perception_runtime
        from sdk.hooks import (
            BeforeChatContext,
            MessageAddedContext,
            PluginHookDispatcher,
            PluginHookEvent,
        )

        self.assertIsNotNone(PerceptionCoordinator)
        self.assertTrue(callable(host_bind_perception_runtime))

        fake_now = [50.0]
        cache = RPInputCache()
        gatekeeper = PerceptionGatekeeper(monotonic_fn=lambda: fake_now[0])
        cache.record_decision(
            PerceptionDigestResult(
                digest="玩家进入新地图篝火点。",
                salience=0.72,
                game="dark_demo",
            )
        )

        dispatcher = PluginHookDispatcher()
        hooks = install_perception_hooks(
            dispatcher,
            rp_input_cache=cache,
            gatekeeper=gatekeeper,
            is_enabled=lambda: True,
        )
        self.assertIs(hooks.gatekeeper, gatekeeper)
        self.assertTrue(dispatcher.has_hooks(PluginHookEvent.BEFORE_CHAT))
        self.assertTrue(dispatcher.has_hooks(PluginHookEvent.MESSAGE_ADDED))

        messages: list[dict[str, object]] = [{"role": "user", "content": "这里安全吗？"}]
        dispatcher.dispatch(
            PluginHookEvent.BEFORE_CHAT,
            BeforeChatContext(messages=messages, tools=None, generation_kwargs={}, stream=True),
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("玩家进入新地图篝火点", str(messages[0]["content"]))

        dispatcher.dispatch(
            PluginHookEvent.MESSAGE_ADDED,
            MessageAddedContext(
                role="assistant",
                message={"role": "assistant", "content": "篝火旁暂时很安全。"},
                messages=messages,
            ),
        )
        self.assertEqual(gatekeeper._last_conversation_activity_at, 50.0)


class TestVisionMemoryAndMoodGate(unittest.TestCase):
    def test_chronological_subtitles_typewriter_merge_and_semantic_protection(self) -> None:
        cache = RPInputCache(max_subtitles=12)
        now = time.time()

        # Out-of-order arrival + typewriter expansion + digit/antonym differences
        cache.record_screen_text("第二句台词", captured_at=now - 8.0)
        cache.record_screen_text("第一句台词", captured_at=now - 10.0)
        cache.record_screen_text("他慢慢走近", captured_at=now - 6.0)
        cache.record_screen_text("他慢慢走近了那座墓碑", captured_at=now - 5.2)
        cache.record_screen_text("剩余生命值 90", captured_at=now - 4.0)
        cache.record_screen_text("剩余生命值 10", captured_at=now - 3.0)

        cache.record_decision(
            PerceptionDigestResult(digest="角色站起看向门口", visual_change="detail", created_at=now - 4.0)
        )
        cache.record_decision(
            PerceptionDigestResult(digest="角色坐下看向门口", visual_change="detail", created_at=now - 2.0)
        )

        context = cache.take_turn_context(allow_consumed_context=True)
        self.assertLess(context.index("第一句台词"), context.index("第二句台词"))
        self.assertLess(context.index("第二句台词"), context.index("他慢慢走近了那座墓碑"))
        self.assertNotIn("* [字幕] 他慢慢走近\n", context)
        self.assertIn("剩余生命值 90", context)
        self.assertIn("剩余生命值 10", context)
        self.assertIn("角色站起看向门口", context)
        self.assertIn("角色坐下看向门口", context)

    def test_galgame_left_aligned_dialogue_box_selected_without_ui_noise(self) -> None:
        def row(left, top, right, bottom, text):
            return ([(left, top), (right, top), (right, bottom), (left, bottom)], text, 0.98)

        rows = [
            row(320, 48, 960, 96, "第一章 星空的证明"),
            row(1040, 560, 1220, 595, "直播间水印"),
            row(180, 540, 860, 575, "不管别人怎么嘲笑，地球确实在转动。"),
            row(180, 584, 430, 618, "请把笔记留下来。"),
        ]
        self.assertEqual(
            select_subtitles(rows, width=1280, height=720),
            "不管别人怎么嘲笑，地球确实在转动。\n请把笔记留下来。",
        )

    def test_seq_watermark_keeps_late_async_ocr_and_supports_followup_turns(self) -> None:
        cache = RPInputCache()
        t0 = time.time()
        cache.record_decision(
            PerceptionDigestResult(digest="雨夜街道上停着一辆马车", salience=0.6, visual_change="cut", created_at=t0 - 4.0)
        )
        cache.record_screen_text("今晚就要出发了", captured_at=t0 - 3.0)

        first_turn = cache.take_turn_context(turn_id="t1", allow_consumed_context=True)
        self.assertIn("今晚就要出发了", first_turn)

        # Async OCR captured BEFORE t1 finished (`t0 - 2.0`), arriving AFTER t1 froze its seq watermark
        cache.record_screen_text("千万别让教会发现", captured_at=t0 - 2.0)

        second_turn_pending = cache.take_turn_context(turn_id="t2", allow_consumed_context=False)
        self.assertIn("千万别让教会发现", second_turn_pending)

        # Immediate manual follow-up question with no new frames still retains context bridge
        followup_turn = cache.take_turn_context(turn_id="t3", allow_consumed_context=True)
        self.assertIn("雨夜街道上停着一辆马车", followup_turn)
        self.assertIn("[上文已看] 千万别让教会发现", followup_turn)

    def test_static_interview_high_salience_subtitle_triggers_proactive_and_adaptive_visual_quota(self) -> None:
        cache = RPInputCache()
        gk = PerceptionGatekeeper()
        cfg = PerceptionConfig(enabled=True, proactive_enabled=True, salience_threshold=0.78)
        now = time.time()

        cache.record_decision(
            PerceptionDigestResult(digest="演播室里嘉宾坐在桌前", salience=0.35, visual_change="cut", created_at=now - 5.0)
        )
        cache.mark_consumed()

        # Static shot (`visual_change="none"`, `digest=""`), pivotal new subtitle with high salience
        cache.record_screen_text("其实那场事故并不是意外。", captured_at=now - 1.0)
        parsed = parse_perception_decision_json(
            '{"mood":"serious","visual_change":"none","digest":"","salience":0.88,'
            '"player_busy":false,"reflex":{"sprite_id":2,"bark":null}}'
        )
        self.assertAlmostEqual(parsed.salience, 0.88)
        cache.record_decision(replace(parsed, created_at=now - 0.5), proactive_threshold=cfg.salience_threshold)

        verdict = gk.evaluate(cache, cfg, chat_busy=False)
        self.assertTrue(verdict.allow)
        proactive_ctx = cache.take_turn_context(proactive=True, salience_threshold=0.78)
        self.assertIn("演播室里嘉宾坐在桌前", proactive_ctx)
        self.assertIn("其实那场事故并不是意外", proactive_ctx)

        # Verify adaptive visual quota: 6 distinct visual beats with no subtitles -> all 6 shown;
        # once >= 4 subtitles arrive -> visual beats tighten to 4.
        cache_visual = RPInputCache()
        for idx in range(6):
            cache_visual.record_decision(
                PerceptionDigestResult(
                    digest=f"玩家探索第{idx + 1}座遗迹石室",
                    visual_change="detail",
                    created_at=now + idx * 0.1,
                )
            )
        visual_heavy_block = cache_visual.format_for_rp_context(consume=False, include_recent_events=True)
        for idx in range(6):
            self.assertIn(f"第{idx + 1}座遗迹石室", visual_heavy_block)

        for idx in range(5):
            cache_visual.record_screen_text(f"碑文记载了第{idx + 1}段历史", captured_at=now + 1.0 + idx * 0.1)
        dialogue_heavy_block = cache_visual.format_for_rp_context(consume=False, include_recent_events=True)
        self.assertIn("当前场景（约 0 秒前）：玩家探索第1座遗迹石室", dialogue_heavy_block)
        self.assertNotIn("第2座遗迹石室", dialogue_heavy_block)
        self.assertIn("第6座遗迹石室", dialogue_heavy_block)

    def test_mood_gate_preserves_short_barks_and_emits_option_b_ambient_bubbles(self) -> None:
        emitted: list[tuple[str, int | None, str]] = []
        responses = iter([
            # 1) `mood="unclear"` suppresses uncertain bark while still switching sprite
            PerceptionDigestResult(
                mood="unclear",
                visual_change="detail",
                digest="模糊的暗影掠过窗户",
                salience=0.35,
                reflex=ReflexDecision(act=True, sprite_id=2, bark="这是什么？"),
            ),
            # 2) `mood="sad"` with empty bark -> Option B emits `"……"` + sad sprite
            PerceptionDigestResult(
                mood="sad",
                visual_change="cut",
                digest="雨中少年跪在墓碑前低头哭泣",
                salience=0.82,
                reflex=ReflexDecision(act=True, sprite_id=3, bark=""),
            ),
            # 3) `mood="sad"` with short empathetic bark -> short bark preserved!
            PerceptionDigestResult(
                mood="sad",
                visual_change="detail",
                digest="少年颤抖着捧起信纸",
                salience=0.75,
                reflex=ReflexDecision(act=True, sprite_id=2, bark="哇……怎么会这样……"),
            ),
            # 4) Silent new scene cut (`bark=""`, `visual_change="cut"`) -> Option B `（看着……）`
            PerceptionDigestResult(
                mood="calm",
                visual_change="cut",
                digest="画面切换到清晨的港口停着一艘帆船，海鸥掠过水面",
                salience=0.45,
                reflex=ReflexDecision(act=False, sprite_id=1, bark=""),
            ),
            # 5) Silent frame with fresh OCR text -> Option B `（正在读：xxxx）`
            PerceptionDigestResult(
                mood="calm",
                visual_change="none",
                digest="",
                ocr_text="第一章：行星运动三定律",
                salience=0.4,
                reflex=ReflexDecision(act=False, sprite_id=None, bark=""),
            ),
            # 6) Consecutive distinct reading text is not suppressed as duplicate wrapper
            PerceptionDigestResult(
                mood="calm",
                visual_change="none",
                digest="",
                ocr_text="第二章：观测记录手稿",
                salience=0.4,
                reflex=ReflexDecision(act=False, sprite_id=None, bark=""),
            ),
        ])

        class FakeDecisionClient:
            def decide(self, _snapshot, _config, **_kwargs):
                return next(responses)

        coordinator = PerceptionCoordinator(
            get_api_config=lambda: SimpleNamespace(
                perception_interval_sec=0.4,
                perception_reflex_cooldown_sec=0.5,
            ),
            resolve_character=lambda: SimpleNamespace(
                name="拉法尔",
                character_brief="理性冷静的少年学者",
                sprites=[{"path": "1.png"}, {"path": "2.png"}, {"path": "3.png"}],
                emotion_tags="立绘 1：平静\n立绘 2：担心\n立绘 3：难过",
            ),
            is_chat_busy=lambda: False,
            apply_reflex=lambda name, sprite, bark: emitted.append((name, sprite, bark)),
            enqueue_proactive_turn=lambda _prompt: False,
            decision_client=FakeDecisionClient(),  # type: ignore[arg-type]
        )
        coordinator.start()
        try:
            coordinator.ingest({"source": "screen_share", "screenShareActive": True, "imageBase64": "ZjA="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(emitted[-1], ("拉法尔", 1, ""))

            time.sleep(0.55)
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZjE="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(emitted[-1], ("拉法尔", 2, "……"))

            time.sleep(0.55)
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZjI="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(emitted[-1], ("拉法尔", 1, "哇……怎么会这样……"))

            time.sleep(0.55)
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZjM="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(emitted[-1], ("拉法尔", 0, "（看着清晨的港口停着一艘帆船……）"))

            time.sleep(0.55)
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZjQ="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(emitted[-1], ("拉法尔", None, "（正在读：第一章：行星运动三定律）"))

            time.sleep(0.55)
            coordinator.ingest({"source": "screen_share", "imageBase64": "ZjU="})
            coordinator.wait_for_buffered_context()
            self.assertEqual(emitted[-1], ("拉法尔", None, "（正在读：第二章：观测记录手稿）"))

            # Ambient bubbles ("……" / "（看着……）" / "（正在读：……）") must not overwrite last spoken bark in RP context
            rp_ctx = coordinator.rp_input_cache.format_for_rp_context(consume=False, include_recent_events=True)
            self.assertIn("哇……怎么会这样……", rp_ctx)
            self.assertNotIn("（看着清晨的港口停着一艘帆船……）", rp_ctx)
            self.assertNotIn("（正在读：", rp_ctx)
            self.assertNotIn("这是什么", rp_ctx)
        finally:
            coordinator.stop()

    def test_episodic_chapters_and_cached_voice_style_extraction(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "voice_styles.json"
            client = PerceptionDecisionClient(voice_style_cache_path=cache_file)
            reply_payload = {
                "choices": [{"message": {"content": "说话风格：拉法尔、理性干脆、自信敏锐、偶带反问"}}]
            }
            resp = io.BytesIO(json.dumps(reply_payload, ensure_ascii=False).encode("utf-8"))
            resp.headers = {"Content-Type": "application/json"}
            with patch.object(client, "_open", return_value=resp) as open_mock:
                style = client.extract_voice_style(
                    "拉法尔",
                    "拉法尔表面圆滑世故，实则痴迷天文学与地动说，说话干脆敏锐。",
                    PerceptionConfig(),
                )
            self.assertEqual(open_mock.call_count, 1)
            self.assertEqual(style, "理性干脆、自信敏锐、偶带反问")
            self.assertNotIn("拉法尔", style)
            self.assertNotIn("地动说", style)

            # Reloading a fresh client reads from disk without hitting the model endpoint
            client2 = PerceptionDecisionClient(voice_style_cache_path=cache_file)
            self.assertEqual(
                client2.get_cached_voice_style(
                    "拉法尔",
                    "拉法尔表面圆滑世故，实则痴迷天文学与地动说，说话干脆敏锐。",
                ),
                "理性干脆、自信敏锐、偶带反问",
            )

        # Episodic chapter compaction when working window overflows
        cache = RPInputCache(max_recent_digests=3, max_subtitles=4, archive_batch_size=4)
        base_ts = time.time() - 180.0
        for idx in range(6):
            cache.record_decision(
                PerceptionDigestResult(
                    digest=f"旅人穿过第{idx + 1}片雪林",
                    visual_change="cut",
                    created_at=base_ts + idx * 5.0,
                )
            )
            cache.record_screen_text(f"风雪越来越大了（第{idx + 1}段）", captured_at=base_ts + idx * 5.0 + 1.0)

        self.assertTrue(cache.needs_episode_compaction())
        batch = cache.pop_archive_batch()
        self.assertGreaterEqual(len(batch), 4)
        cache.append_episode(
            "旅人顶着风雪连续穿过数片雪林，台词提到风雪愈发猛烈。",
            start_ts=batch[0][0],
            end_ts=batch[-1][0],
            mood="tense",
        )
        # Toggling screen share preserves session episodes until explicit clear()
        cache.reset_working_window_preserving_episodes()
        cache.record_decision(
            PerceptionDigestResult(digest="旅人推开木屋大门", visual_change="cut", created_at=time.time())
        )
        rendered = cache.format_for_rp_context(consume=False, include_recent_events=True)
        self.assertIn("前情纪要（按时间顺序）", rendered)
        self.assertIn("旅人顶着风雪连续穿过数片雪林", rendered)
        self.assertIn("旅人推开木屋大门", rendered)


if __name__ == "__main__":
    unittest.main()

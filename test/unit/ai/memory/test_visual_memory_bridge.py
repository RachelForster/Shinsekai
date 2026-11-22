"""Unit tests for Multimodal Visual Memory Bridge (MIRIX + M3-Agent + WorldMM)."""

from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path

import pytest

from ai.memory import operations
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.engine import HybridMemoryEngine
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.queue import MemoryWriteQueue
from ai.memory.visual_bridge import reinspect_visual_memory
from ai.vision.message_content import LOCAL_IMAGE_BLOCK_TYPE
from application.perception.hooks import PerceptionAutoHooks
from core.chat_history.identity import CHAT_TURN_ID
from core.media.chat_attachments import CHAT_ATTACHMENTS_ROOT_ENV
from core.perception.cache import RPInputCache
from core.perception.gatekeeper import PerceptionGatekeeper
from core.perception.models import PerceptionDigestResult
from sdk.adapters.memory import TurnRecallInput
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher
from test.mocks import MockLLMAdapter


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0).timestamp()


class _StubVisionDescriber:
    def __init__(self, caption: str) -> None:
        self.caption = caption
        self.calls: list[tuple[int, str]] = []

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        self.calls.append((len(image_bytes), prompt))
        return self.caption


def test_fallback_and_native_chat_images_persist_visual_memories_vault_ref_and_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(tmp_path))
    stage_dir = tmp_path / "data" / "chat_attachments" / "uuid123"
    stage_dir.mkdir(parents=True)
    img_file = stage_dir / "calico_cat.png"
    png_bytes = b"\x89PNG\r\n\x1a\nfake-cat-image-bytes"
    img_file.write_bytes(png_bytes)

    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "visual_mem.db")
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    try:
        # --- Case 1: Fallback vision mode (`display_content` masks content as `[image: calico_cat.png]`) ---
        fallback_extract_resp = json.dumps(
            [
                {
                    "character_name": "Mika",
                    "detail": "用户发来照片展示自家三花猫糯米团趴在发光机械键盘上睡觉",
                    "gist": "看过三花猫糯米团趴键盘的照片",
                    "kind": "visual",
                    "topics": ["宠物", "照片"],
                    "entities": ["糯米团", "三花猫", "机械键盘"],
                    "importance": 0.85,
                }
            ],
            ensure_ascii=False,
        )
        describer = _StubVisionDescriber("不应在Fallback模式下重复调用")
        llm1 = MockLLMAdapter(responses=[fallback_extract_resp])
        hooks1 = MemoryAutoHooks(
            llm_adapter=llm1,
            character_names=["Mika"],
            session_id="sess-vis",
            memory_mode="shared",
            queue=MemoryWriteQueue(path=tmp_path / "q1.json"),
            extract_interval_turns=1,
            vision_describer_factory=lambda: describer,
        )

        fallback_user_msg = {
            "role": "user",
            "display_content": "给你看我家主子\n[image: calico_cat.png]",
            "content": (
                "给你看我家主子\n\n"
                "Image attachment calico_cat.png:\n"
                "一只圆滚滚的三花猫正趴在RGB机械键盘上打呼噜。"
            ),
            "attachments": [
                {
                    "kind": "image",
                    "mimeType": "image/png",
                    "name": "calico_cat.png",
                    "path": str(img_file),
                    "size": len(png_bytes),
                }
            ],
        }
        hooks1.message_added(
            MessageAddedContext(
                role="user",
                message=fallback_user_msg,
                messages=[],
                session_id="sess-vis",
                turn_seq=3,
            )
        )
        hooks1.message_added(
            MessageAddedContext(
                role="assistant",
                message={"role": "assistant", "content": "哇！糯米团压住键盘的样子太可爱啦！"},
                messages=[],
                session_id="sess-vis",
                turn_seq=4,
            )
        )
        hooks1.wait_for_idle()

        # Verify precomputed fallback description was forwarded into extraction prompt with ZERO VLM re-calls!
        assert describer.calls == []
        sent_prompt = llm1.call_history[0]["messages"][-1]["content"]
        assert "三花猫正趴在RGB机械键盘上打呼噜" in sent_prompt

        # Verify `kind="visual"`, `[视觉记忆]` rendering, and clean `visualRef` vault pointer!
        search_res = operations.memory_search("三花猫糯米团趴键盘的照片", character_name="Mika")
        assert search_res["count"] == 1
        hit = search_res["memories"][0]
        assert hit["kind"] == "visual"
        assert hit["visualRef"] == "data/chat_attachments/uuid123/calico_cat.png"
        assert hit["rendered"].startswith("[视觉记忆]")
        assert all(not t.startswith("__sys:") for t in hit["topicTags"])

        # --- WorldMM On-Demand Pixel Re-inspection via `reinspect_visual_memory` ---
        fine_describer = _StubVisionDescriber("键盘右上角贴着一张宇航员小贴纸，键帽是奶白色。")
        reinspected = reinspect_visual_memory(
            hit["visualRef"],
            "键盘右上角贴着什么？",
            describer=fine_describer,
            attachments_root=tmp_path,
        )
        assert reinspected["ok"] is True
        assert "宇航员小贴纸" in reinspected["answer"]
        assert len(fine_describer.calls) == 1

        # Path traversal attempt is strictly rejected
        traversal = reinspect_visual_memory(
            "../../outside_secret.png",
            "test",
            describer=fine_describer,
            attachments_root=tmp_path,
        )
        assert traversal["ok"] is False

        # --- Case 2: Native `local_image` mode captions asynchronously & supports rollback ---
        img_file_2 = stage_dir / "ramen_ticket.png"
        img_file_2.write_bytes(png_bytes)
        native_describer = _StubVisionDescriber("一碗浓汤豚骨拉面，溏心蛋旁放着两片叉烧。")
        native_extract_resp = json.dumps(
            [
                {
                    "character_name": "Mika",
                    "detail": "用户深夜分享了一碗加了两片叉烧和溏心蛋的浓汤豚骨拉面照片",
                    "gist": "深夜分享浓汤豚骨拉面照片",
                    "kind": "episodic",  # Auto-upgraded to `visual` when window has image ref!
                    "entities": ["豚骨拉面"],
                    "importance": 0.75,
                }
            ],
            ensure_ascii=False,
        )
        llm2 = MockLLMAdapter(responses=[native_extract_resp])
        hooks2 = MemoryAutoHooks(
            llm_adapter=llm2,
            character_names=["Mika"],
            session_id="sess-vis",
            memory_mode="shared",
            queue=MemoryWriteQueue(path=tmp_path / "q2.json"),
            extract_interval_turns=1,
            vision_describer_factory=lambda: native_describer,
        )
        native_user_msg = {
            "role": "user",
            "display_content": "夜宵放毒\n[image: ramen_ticket.png]",
            "content": [
                {"type": "text", "text": "夜宵放毒"},
                {
                    "type": LOCAL_IMAGE_BLOCK_TYPE,
                    "media_type": "image/png",
                    "name": "ramen_ticket.png",
                    "path": str(img_file_2),
                    "data": base64.b64encode(png_bytes).decode("ascii"),
                },
            ],
        }
        hooks2.message_added(
            MessageAddedContext(
                role="user",
                message=native_user_msg,
                messages=[],
                session_id="sess-vis",
                turn_seq=7,
            )
        )
        hooks2.message_added(
            MessageAddedContext(
                role="assistant",
                message={"role": "assistant", "content": "大半夜看饿了！"},
                messages=[],
                session_id="sess-vis",
                turn_seq=8,
            )
        )
        hooks2.wait_for_idle()
        assert len(native_describer.calls) == 1

        ramen_hits = operations.memory_search("浓汤豚骨拉面照片", character_name="Mika")
        assert ramen_hits["count"] >= 1
        assert ramen_hits["memories"][0]["kind"] == "visual"
        assert ramen_hits["memories"][0]["visualRef"] == "data/chat_attachments/uuid123/ramen_ticket.png"

        # Rollback session `sess-vis` to turn 5 -> ramen visual memory (turn 8) rolls back cleanly,
        # while calico cat visual memory (turn 4) remains intact!
        global_repo.rollback_after_turn("sess-vis", 5)
        remaining = operations.memory_list("Mika")["memories"]
        assert len(remaining) == 1
        assert "糯米团" in remaining[0]["detail"]
    finally:
        global_repo.close()


def test_screen_companion_tier1_perception_promotes_to_tier2_graph_on_dialogue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "companion_vis.db")
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    try:
        extract_resp = json.dumps(
            [
                {
                    "character_name": "Mika",
                    "detail": "Mika陪用户打《黑神话：悟空》卡关一小时后终于残血反杀虎先锋",
                    "gist": "一起打过黑神话虎先锋",
                    "kind": "visual",
                    "entities": ["虎先锋"],  # Bridge auto-injects `active_game` ("黑神话：悟空")!
                    "importance": 0.9,
                }
            ],
            ensure_ascii=False,
        )
        llm = MockLLMAdapter(responses=[extract_resp])
        dispatcher = PluginHookDispatcher()

        rp_cache = RPInputCache()
        perc_hooks = PerceptionAutoHooks(
            rp_input_cache=rp_cache,
            gatekeeper=PerceptionGatekeeper(),
            is_enabled=lambda: True,
        )
        perc_hooks.register(dispatcher)

        mem_hooks = MemoryAutoHooks(
            llm_adapter=llm,
            character_names=["Mika"],
            session_id="sess-game",
            memory_mode="shared",
            queue=MemoryWriteQueue(path=tmp_path / "q_game.json"),
            extract_interval_turns=1,
        )
        mem_hooks.register(dispatcher)

        now_ts = _ts(2026, 11, 16, 20)
        rp_cache.record_decision(
            PerceptionDigestResult(
                digest="卧虎寺血池中天命人仅剩一丝血，铜头铁臂弹反击败Boss虎先锋",
                salience=0.95,
                mood="excited",
                game="黑神话：悟空",
                created_at=now_ts,
            )
        )
        assert perc_hooks.prepare_turn("turn-user-game-1", "user") is True

        # Follow exact production `llm_manager` call order: `message_added(user)` BEFORE `before_chat`!
        user_msg = {
            "role": "user",
            CHAT_TURN_ID: "turn-user-game-1",
            "display_content": "手都在抖，终于过了！！",
            "content": "手都在抖，终于过了！！",
        }
        dispatcher.dispatch_message_added(
            MessageAddedContext(
                role="user",
                message=user_msg,
                messages=[user_msg],
                session_id="sess-game",
                turn_seq=1,
            )
        )
        dispatcher.dispatch_before_chat(
            BeforeChatContext(
                messages=[{"role": "system", "content": "S"}, user_msg],
                tools=None,
                generation_kwargs={},
                stream=False,
            )
        )
        dispatcher.dispatch_message_added(
            MessageAddedContext(
                role="assistant",
                message={"role": "assistant", "content": "刚才那下铜头铁臂太帅啦！"},
                messages=[],
                session_id="sess-game",
                turn_seq=2,
            )
        )
        mem_hooks.wait_for_idle()

        # Verify extraction prompt received the real game perception summary despite `display_content`!
        prompt_sent = llm.call_history[0]["messages"][-1]["content"]
        assert "黑神话：悟空" in prompt_sent
        assert "虎先锋" in prompt_sent

        # Verify `active_game` ("黑神话：悟空") was anchored in `entities` and recalls after screen share ends!
        recalled = engine.orchestrator.recall_for_turn(
            TurnRecallInput(
                user_text="上次我们一起玩黑神话悟空打过了哪个Boss？",
                active_character_names=("Mika",),
                session_id="sess-game",
                in_window_turn_seqs=frozenset({20, 21}),
                now_ts=now_ts + 3600,
            )
        )
        assert "虎先锋" in recalled.rendered
        assert "[视觉记忆]" in recalled.rendered
    finally:
        global_repo.close()

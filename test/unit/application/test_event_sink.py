import unittest

from application.runtime.event_sink import (
    fold_event_into_snapshot,
    make_empty_chat_snapshot,
)


class EventSinkSnapshotTests(unittest.TestCase):
    def test_active_voice_and_loop_effects_are_folded_for_recovery(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "characterName": "Mio",
                "playbackId": "voice-1",
                "rendererId": "renderer-desktop",
                "seq": 4,
                "type": "tts.play",
                "url": "/api/media?path=voice.wav",
                "volume": 0.7,
            },
        )
        snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "key": "rain",
                "seq": 5,
                "type": "effect.loop.start",
                "url": "/api/media?path=rain.wav",
            },
        )
        snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 6,
                "type": "effect.play",
                "url": "/api/media?path=impact.wav",
            },
        )

        self.assertEqual(
            snapshot["activePlayback"],
            {
                "characterName": "Mio",
                "playbackId": "voice-1",
                "rendererId": "renderer-desktop",
                "seq": 4,
                "url": "/api/media?path=voice.wav",
                "volume": 0.7,
            },
        )
        self.assertEqual(
            snapshot["loopingEffects"],
            [{"key": "rain", "seq": 5, "url": "/api/media?path=rain.wav"}],
        )

        stopped = fold_event_into_snapshot(
            snapshot,
            {"playbackId": "voice-1", "seq": 7, "type": "tts.skip"},
        )
        stopped = fold_event_into_snapshot(
            stopped,
            {"key": "rain", "seq": 8, "type": "effect.loop.stop"},
        )
        self.assertIsNone(stopped["activePlayback"])
        self.assertEqual(stopped["loopingEffects"], [])

    def test_stats_are_folded_for_reconnect_without_replacing_token_usage(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["numericInfo"] = "tokens total 42"

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 1,
                "stats": [
                    {"icon": "heart", "label": "HP", "max": 100, "value": 72},
                    {"icon": "coins", "label": "Gold", "value": 320},
                    {"icon": "gauge", "label": "Broken", "value": float("nan")},
                ],
                "ts": 1,
                "type": "stats.update",
                "v": 1,
            },
        )

        self.assertEqual(
            next_snapshot["stats"],
            [
                {"icon": "heart", "label": "HP", "max": 100, "value": 72},
                {"icon": "coins", "label": "Gold", "value": 320},
            ],
        )
        self.assertEqual(next_snapshot["numericInfo"], "tokens total 42")

    def test_background_and_bgm_changes_are_folded_for_reconnect(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "seq": 1,
                "ts": 1,
                "type": "background.change",
                "url": "asset://room.png",
                "v": 1,
            },
        )
        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 2,
                "ts": 2,
                "type": "bgm.change",
                "url": "asset://room.mp3",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot["backgroundPath"], "asset://room.png")
        self.assertEqual(next_snapshot["bgmPath"], "asset://room.mp3")

    def test_sprite_show_replaces_the_previous_slot_occupant_and_preserves_axes(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "characterName": "Mio",
                "scale": 1.0,
                "seq": 1,
                "slot": 0,
                "ts": 1,
                "type": "sprite.show",
                "url": "asset://mio.png",
                "v": 1,
            },
        )
        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "characterName": "Ren",
                "scale": 0.9,
                "seq": 2,
                "slot": 0,
                "ts": 2,
                "type": "sprite.show",
                "url": "asset://ren.png",
                "v": 1,
                "x": 18,
                "y": -12,
            },
        )

        self.assertEqual(
            next_snapshot["sprites"],
            [
                {
                    "characterName": "Ren",
                    "id": "Ren:0",
                    "label": "Ren",
                    "path": "asset://ren.png",
                    "scale": 0.9,
                    "slot": 0,
                    "x": 18,
                    "y": -12,
                }
            ],
        )

    def test_sprite_snapshot_preserves_most_recent_foreground_order(self):
        snapshot = make_empty_chat_snapshot()
        for seq, name, slot in ((1, "Mio", 0), (2, "Aoi", 2), (3, "Mio", 0)):
            snapshot = fold_event_into_snapshot(
                snapshot,
                {
                    "characterName": name,
                    "scale": 1.0,
                    "seq": seq,
                    "slot": slot,
                    "ts": seq,
                    "type": "sprite.show",
                    "url": f"asset://{name.lower()}-{seq}.png",
                    "v": 1,
                },
            )

        self.assertEqual(
            [(sprite["characterName"], sprite["slot"]) for sprite in snapshot["sprites"]],
            [("Aoi", 2), ("Mio", 0)],
        )
        self.assertEqual(snapshot["sprites"][-1]["path"], "asset://mio-3.png")

    def test_chat_init_progress_is_folded_into_snapshot_and_sanitized(self):
        snapshot = make_empty_chat_snapshot()

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 1,
                "ts": 1,
                "type": "chat.init.progress",
                "task": {
                    "message": "Loading memory",
                    "phase": "memory",
                    "progress": 1.5,
                    "status": "succeeded",
                    "logs": ["first", "second"],
                    "result": {"must": "not be folded"},
                },
                "v": 1,
            },
        )

        self.assertEqual(
            next_snapshot["initTask"],
            {
                "message": "Loading memory",
                "phase": "memory",
                "progress": 1.0,
                "status": "running",
                "logs": ["first", "second"],
            },
        )

    def test_chat_init_terminal_events_override_status_and_preserve_progress_fields(self):
        progress_snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "seq": 1,
                "ts": 1,
                "type": "chat.init.progress",
                "task": {"message": "Starting TTS", "phase": "tts", "progress": 0.4},
                "v": 1,
            },
        )

        completed_snapshot = fold_event_into_snapshot(
            progress_snapshot,
            {
                "seq": 2,
                "ts": 2,
                "type": "chat.init.completed",
                "task": {"message": "Ready", "phase": "completed"},
                "v": 1,
            },
        )

        self.assertEqual(completed_snapshot["initTask"]["status"], "succeeded")
        self.assertEqual(completed_snapshot["initTask"]["progress"], 1.0)
        self.assertEqual(completed_snapshot["initTask"]["message"], "Ready")

        failed_snapshot = fold_event_into_snapshot(
            progress_snapshot,
            {
                "seq": 2,
                "ts": 2,
                "type": "chat.init.failed",
                "task": {"error": "TTS failed", "message": "Could not start TTS"},
                "v": 1,
            },
        )
        self.assertEqual(failed_snapshot["initTask"]["status"], "failed")
        self.assertEqual(failed_snapshot["initTask"]["error"], "TTS failed")
        self.assertEqual(failed_snapshot["initTask"]["phase"], "tts")

        cancelled_snapshot = fold_event_into_snapshot(
            progress_snapshot,
            {
                "seq": 2,
                "ts": 2,
                "type": "chat.init.cancelled",
                "task": {"message": "Cancelled"},
                "v": 1,
            },
        )
        self.assertEqual(cancelled_snapshot["initTask"]["status"], "cancelled")

    def test_named_system_dialog_end_preserves_speaker_name(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["characterName"] = "Nanami"

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 2,
                "ts": 2,
                "type": "dialog.end",
                "speaker": "旁白",
                "color": "#84C2D5",
                "isSystem": True,
                "fullHtml": "<p><b>旁白</b>：新的系统消息</p>",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot["dialogText"], "旁白：新的系统消息")
        self.assertEqual(next_snapshot.get("characterName"), "旁白")

    def test_speakerless_system_dialog_survives_status_updates_for_reconnect(self):
        initial_snapshot = make_empty_chat_snapshot()
        initial_snapshot["characterName"] = "Nanami"
        snapshot = fold_event_into_snapshot(
            initial_snapshot,
            {
                "seq": 1,
                "ts": 1,
                "type": "dialog.end",
                "speaker": "",
                "color": "#84C2D5",
                "isSystem": True,
                "fullHtml": "<p>Waiting for chat</p>",
                "v": 1,
            },
        )
        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {"seq": 2, "ts": 2, "type": "status.change", "status": "idle", "v": 1},
        )

        self.assertEqual(snapshot.get("characterName"), "")
        self.assertEqual(next_snapshot.get("systemMessageText"), "Waiting for chat")

    def test_session_closed_clears_busy_overlay_fields_in_snapshot(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["busyText"] = "Loading"
        snapshot["busyDurationSeconds"] = 3.0
        snapshot["options"] = ["继续"]
        snapshot["status"] = "generating"
        snapshot["toolConfirmation"] = {
            "confirmationId": "prompt-1",
            "detail": "",
            "risk": "high",
            "toolName": "file_write",
        }

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 3,
                "ts": 3,
                "type": "session.closed",
                "reason": "聊天会话已结束。",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("busyText"), "")
        self.assertEqual(next_snapshot.get("busyDurationSeconds"), 0.0)
        self.assertEqual(next_snapshot.get("options"), [])
        self.assertEqual(next_snapshot.get("notificationText"), "聊天会话已结束。")
        self.assertEqual(next_snapshot.get("sessionClosedReason"), "聊天会话已结束。")
        self.assertEqual(next_snapshot.get("status"), "idle")
        self.assertIsNone(next_snapshot.get("toolConfirmation"))

    def test_tool_confirmation_is_folded_and_only_matching_clear_removes_it(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "confirmationId": "prompt-1",
                "detail": r"path=D:\notes\plan.txt",
                "risk": "high",
                "seq": 1,
                "toolName": "file_write",
                "ts": 1,
                "type": "tool.confirmation.show",
                "v": 1,
            },
        )

        stale_clear = fold_event_into_snapshot(
            snapshot,
            {
                "confirmationId": "prompt-old",
                "seq": 2,
                "ts": 2,
                "type": "tool.confirmation.clear",
                "v": 1,
            },
        )
        matching_clear = fold_event_into_snapshot(
            stale_clear,
            {
                "confirmationId": "prompt-1",
                "seq": 3,
                "ts": 3,
                "type": "tool.confirmation.clear",
                "v": 1,
            },
        )

        self.assertEqual(snapshot["toolConfirmation"]["confirmationId"], "prompt-1")
        self.assertEqual(stale_clear["toolConfirmation"]["confirmationId"], "prompt-1")
        self.assertIsNone(matching_clear["toolConfirmation"])

    def test_asr_state_clears_stale_closed_session_reason_in_snapshot(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["notificationText"] = "聊天会话已结束。"
        snapshot["sessionClosedReason"] = "聊天会话已结束。"
        snapshot["status"] = "idle"

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 4,
                "ts": 4,
                "type": "asr.state",
                "running": False,
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("sessionClosedReason"), "")
        self.assertEqual(next_snapshot.get("notificationText"), "")
        self.assertEqual(next_snapshot.get("status"), "paused")
        self.assertFalse(next_snapshot.get("asrEnabled"))
        self.assertFalse(next_snapshot.get("asrLoading"))
        self.assertFalse(next_snapshot.get("asrRunning"))

    def test_asr_final_snapshot_persists_consumed_transcript_state(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["inputDraft"] = "hello wor"
        snapshot["options"] = ["stale option"]

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 5,
                "text": "hello world",
                "ts": 5,
                "type": "asr.final",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("inputDraft"), "")
        self.assertEqual(next_snapshot.get("options"), [])

    def test_ided_asr_final_only_clears_the_matching_utterance_draft(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "seq": 1,
                "text": "hello",
                "ts": 1,
                "type": "asr.partial",
                "utteranceId": "u-old",
                "v": 1,
            },
        )
        snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 2,
                "text": "hello there",
                "ts": 2,
                "type": "asr.partial",
                "utteranceId": "u-new",
                "v": 1,
            },
        )

        older_final = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 3,
                "text": "hello",
                "ts": 3,
                "type": "asr.final",
                "utteranceId": "u-old",
                "v": 1,
            },
        )
        self.assertEqual(older_final.get("inputDraft"), "hello there")
        self.assertEqual(older_final.get("asrUtteranceId"), "u-new")

        matching_final = fold_event_into_snapshot(
            older_final,
            {
                "seq": 4,
                "text": "hello there",
                "ts": 4,
                "type": "asr.final",
                "utteranceId": "u-new",
                "v": 1,
            },
        )
        self.assertEqual(matching_final.get("inputDraft"), "")
        self.assertIsNone(matching_final.get("asrUtteranceId"))

    def test_ided_asr_final_preserves_a_non_asr_owned_draft(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["inputDraft"] = "manual draft"
        snapshot["asrUtteranceId"] = None

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 2,
                "text": "voice draft",
                "ts": 2,
                "type": "asr.final",
                "utteranceId": "u-voice",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("inputDraft"), "manual draft")
        self.assertIsNone(next_snapshot.get("asrUtteranceId"))

    def test_ided_empty_asr_partial_starts_a_fresh_owned_draft(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "seq": 1,
                "text": "old voice",
                "ts": 1,
                "type": "asr.partial",
                "utteranceId": "u-old",
                "v": 1,
            },
        )
        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 2,
                "text": "",
                "ts": 2,
                "type": "asr.partial",
                "utteranceId": "u-reset",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("inputDraft"), "")
        self.assertEqual(next_snapshot.get("asrUtteranceId"), "u-reset")

    def test_legacy_asr_final_still_clears_a_corrected_transcript_draft(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "seq": 1,
                "text": "hello word",
                "ts": 1,
                "type": "asr.partial",
                "v": 1,
            },
        )
        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 2,
                "text": "hello world",
                "ts": 2,
                "type": "asr.final",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("inputDraft"), "")
        self.assertIsNone(next_snapshot.get("asrUtteranceId"))

    def test_asr_state_preserves_reply_status_while_listening_is_temporarily_paused(
        self,
    ):
        snapshot = make_empty_chat_snapshot()
        snapshot["status"] = "generating"
        snapshot["asrEnabled"] = True
        snapshot["asrRunning"] = True

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "enabled": True,
                "loading": False,
                "running": False,
                "seq": 5,
                "ts": 5,
                "type": "asr.state",
                "v": 1,
            },
        )

        self.assertTrue(next_snapshot.get("asrEnabled"))
        self.assertFalse(next_snapshot.get("asrLoading"))
        self.assertFalse(next_snapshot.get("asrRunning"))
        self.assertEqual(next_snapshot.get("status"), "generating")

    def test_asr_partial_and_running_state_preserve_active_reply_status(self):
        for status in ("generating", "streaming", "speaking"):
            snapshot = make_empty_chat_snapshot()
            snapshot["status"] = status

            with_partial = fold_event_into_snapshot(
                snapshot,
                {
                    "seq": 5,
                    "text": "next message",
                    "ts": 5,
                    "type": "asr.partial",
                    "v": 1,
                },
            )
            with_running_state = fold_event_into_snapshot(
                with_partial,
                {
                    "enabled": True,
                    "loading": False,
                    "running": True,
                    "seq": 6,
                    "ts": 6,
                    "type": "asr.state",
                    "v": 1,
                },
            )

            self.assertEqual(with_partial.get("inputDraft"), "next message")
            self.assertEqual(with_partial.get("status"), status)
            self.assertEqual(with_running_state.get("status"), status)

    def test_reply_finished_clears_stale_notification_text_in_snapshot(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["notificationText"] = "您的消息已提交，正在等待 LLM 处理..."
        snapshot["status"] = "generating"

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 5,
                "ts": 5,
                "type": "reply.finished",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("notificationText"), "")
        self.assertEqual(next_snapshot.get("status"), "idle")

    def test_admitted_asr_final_preserves_a_newer_voice_draft(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["inputDraft"] = "newer phrase"
        snapshot["asrUtteranceId"] = "u-newer"

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 5,
                "text": "earlier phrase",
                "ts": 5,
                "type": "asr.final",
                "utteranceId": "u-earlier",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("inputDraft"), "newer phrase")

    def test_user_display_name_change_updates_snapshot(self):
        snapshot = make_empty_chat_snapshot()

        next_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 6,
                "ts": 6,
                "type": "user.display_name.change",
                "name": "澪",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("userDisplayName"), "澪")

    def test_dialog_end_clears_start_options_after_first_real_line(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["options"] = ["开始"]

        welcome_snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "seq": 6,
                "ts": 6,
                "type": "dialog.end",
                "speaker": "",
                "color": "#84C2D5",
                "isSystem": True,
                "fullHtml": "<p>欢迎</p>",
                "v": 1,
            },
        )
        self.assertEqual(welcome_snapshot.get("options"), ["开始"])

        next_snapshot = fold_event_into_snapshot(
            welcome_snapshot,
            {
                "seq": 7,
                "ts": 7,
                "type": "dialog.end",
                "speaker": "旁白",
                "color": "#84C2D5",
                "isSystem": True,
                "fullHtml": "<p><b>旁白</b>：正式首句</p>",
                "v": 1,
            },
        )

        self.assertEqual(next_snapshot.get("options"), [])

    def test_chat_turn_state_is_folded_into_reconnect_snapshot(self):
        next_snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "seq": 8,
                "options": {
                    "batchEnabled": True,
                    "batchIdleSeconds": 6.5,
                    "interruptEnabled": False,
                },
                "state": {
                    "enabled": True,
                    "pendingCount": 2,
                    "pendingMessages": ["message A", "message B"],
                    "remainingSeconds": 4,
                    "scheduled": True,
                    "typing": False,
                },
                "ts": 8,
                "type": "chat.turn.state",
                "v": 1,
            },
        )

        self.assertEqual(
            next_snapshot["turnState"],
            {
                "enabled": True,
                "pendingCount": 2,
                "pendingMessages": ["message A", "message B"],
                "remainingSeconds": 4,
                "scheduled": True,
                "typing": False,
            },
        )
        self.assertEqual(
            next_snapshot["turnOptions"],
            {
                "batchEnabled": True,
                "batchIdleSeconds": 6.5,
                "interruptEnabled": False,
            },
        )

    def test_plugin_page_presentations_are_folded_and_dismissed_for_reconnect(self):
        presented = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {
                "mode": "overlay",
                "pageId": "dashboard",
                "payload": {"kind": "reminder"},
                "pluginId": "demo.plugin",
                "presentationId": "notice-42",
                "seq": 9,
                "ts": 9,
                "type": "plugin.page.present",
                "v": 1,
            },
        )

        self.assertEqual(
            presented["pluginPagePresentations"],
            [
                {
                    "mode": "overlay",
                    "pageId": "dashboard",
                    "payload": {"kind": "reminder"},
                    "pluginId": "demo.plugin",
                    "presentationId": "notice-42",
                }
            ],
        )

        dismissed = fold_event_into_snapshot(
            presented,
            {
                "pluginId": "demo.plugin",
                "presentationId": "notice-42",
                "seq": 10,
                "ts": 10,
                "type": "plugin.page.dismiss",
                "v": 1,
            },
        )

        self.assertEqual(dismissed["pluginPagePresentations"], [])


class StoryEventSinkTests(unittest.TestCase):
    def test_structured_options_and_story_state_survive_snapshot_folding(self):
        option = {
            "enabled": True,
            "expectedNodeId": "gate",
            "expectedRevision": 3,
            "id": "enter",
            "label": "Enter",
            "source": "story",
        }
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
            {"type": "options.show", "options": ["Wait", option]},
        )
        snapshot = fold_event_into_snapshot(
            snapshot,
            {
                "type": "story.state.replace",
                "story": {"currentNodeId": "gate", "options": [option]},
            },
        )

        self.assertEqual(snapshot["options"], [option])
        self.assertEqual(snapshot["story"]["currentNodeId"], "gate")


if __name__ == "__main__":
    unittest.main()

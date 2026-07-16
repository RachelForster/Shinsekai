import unittest

from core.runtime.event_sink import fold_event_into_snapshot, make_empty_chat_snapshot


class EventSinkSnapshotTests(unittest.TestCase):
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

    def test_system_dialog_end_clears_stale_character_name(self):
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
        self.assertEqual(next_snapshot.get("characterName"), "")

    def test_speakerless_system_dialog_survives_status_updates_for_reconnect(self):
        snapshot = fold_event_into_snapshot(
            make_empty_chat_snapshot(),
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

        self.assertEqual(next_snapshot.get("systemMessageText"), "Waiting for chat")

    def test_session_closed_clears_busy_overlay_fields_in_snapshot(self):
        snapshot = make_empty_chat_snapshot()
        snapshot["busyText"] = "Loading"
        snapshot["busyDurationSeconds"] = 3.0
        snapshot["options"] = ["继续"]
        snapshot["status"] = "generating"

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


if __name__ == "__main__":
    unittest.main()

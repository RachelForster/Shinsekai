from __future__ import annotations

import json
import threading
from collections import deque

from core.runtime.app_runtime import get_app_runtime
from sdk.graph import DagNode, Port


class ScriptedLiveBridgeNode(DagNode):
    PORT_USER_INPUT = "user_input"
    PORT_AUDIO_OUTPUT = "audio_output"

    def __init__(self, name: str = "scripted_live_bridge") -> None:
        super().__init__(name)
        self._thread: threading.Thread | None = None
        self._speech_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._active_options: list[str] = []
        self._pending_advances: deque[str] = deque()
        self._message_counts: dict[str, int] = {}
        self._speaking_active = False
        self._speaking_skip_requested = threading.Event()
        self._speaking_text: str | None = None

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_USER_INPUT: Port(self.PORT_USER_INPUT)}

    def outputs(self) -> dict[str, Port]:
        return {self.PORT_AUDIO_OUTPUT: Port(self.PORT_AUDIO_OUTPUT)}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._speaking_skip_requested.set()
        try:
            self.inq(self.PORT_USER_INPUT).put(None)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._speech_thread is not None:
            self._speech_thread.join(timeout=2.0)
        self._thread = None
        self._speech_thread = None

    def skip_speech(self) -> None:
        pending: str | None = None
        speaking = False
        with self._lock:
            if self._speaking_active:
                speaking = True
            elif self._pending_advances:
                pending = self._pending_advances.popleft()
        if speaking:
            self._speaking_skip_requested.set()
            return
        if pending:
            self._emit_dialog(pending)

    def _run(self) -> None:
        queue = self.inq(self.PORT_USER_INPUT)
        while self._running:
            item = queue.get()
            try:
                if item is None:
                    break
                text = str(getattr(item, "text", "") or "").strip()
                if text:
                    self._handle_user_text(text)
            finally:
                queue.task_done()

    def _handle_user_text(self, text: str) -> None:
        runtime = get_app_runtime()
        ui = runtime.ui_update_manager
        runtime.llm_manager.add_message("user", text)
        ui.record_user_message(text)
        with self._lock:
            active_options = list(self._active_options)
        if active_options and text in active_options:
            ui.post_options([])
            with self._lock:
                self._active_options = []
                self._pending_advances.clear()
                self._pending_advances.append("下一段已展开。")
            self._emit_dialog(f"已选择：{text}")
            return

        if text == "触发打断测试":
            if active_options:
                ui.post_options([])
            with self._lock:
                self._active_options = []
                self._pending_advances.clear()
            self._start_interruptible_speech("语音已打断：触发打断测试")
            return

        if text == "触发关闭恢复测试":
            if active_options:
                ui.post_options([])
            with self._lock:
                self._active_options = []
                self._pending_advances.clear()
            ui.post_session_closed("聊天会话已结束。")
            return

        if text == "触发重试测试":
            with self._lock:
                count = self._message_counts.get(text, 0) + 1
                self._message_counts[text] = count
                self._active_options = ["继续剧情", "结束测试"]
                self._pending_advances.clear()
                self._pending_advances.append("下一段已展开。")
            self._emit_dialog(f"收到消息：{text}（第{count}次）")
            ui.post_options(["继续剧情", "结束测试"])
            return

        next_options = ["继续剧情", "结束测试"]
        with self._lock:
            self._active_options = list(next_options)
            self._pending_advances.clear()
            self._pending_advances.append("下一段已展开。")
        self._emit_dialog(f"收到消息：{text}")
        ui.post_options(next_options)

    def _start_interruptible_speech(self, final_text: str) -> None:
        runtime = get_app_runtime()
        ui = runtime.ui_update_manager
        with self._lock:
            self._speaking_active = True
            self._speaking_text = final_text
            self._speaking_skip_requested.clear()
        ui.post_tts_play("直播桥接测试", "test/audio/live-bridge-speaking.wav")
        self._speech_thread = threading.Thread(
            target=self._complete_interruptible_speech,
            name=f"{self.name}-speech",
            daemon=True,
        )
        self._speech_thread.start()

    def _complete_interruptible_speech(self) -> None:
        skipped = self._speaking_skip_requested.wait(timeout=5.0)
        if not self._running:
            return
        with self._lock:
            if not self._speaking_active:
                return
            self._speaking_active = False
            final_text = self._speaking_text or "语音已结束。"
            self._speaking_text = None
        ui = get_app_runtime().ui_update_manager
        if skipped:
            ui.post_tts_skip()
        self._emit_dialog(final_text)

    def _emit_dialog(self, text: str) -> None:
        runtime = get_app_runtime()
        ui = runtime.ui_update_manager
        runtime.llm_manager.add_message(
            "assistant",
            json.dumps(
                {
                    "dialog": [
                        {
                            "character_name": "直播桥接测试",
                            "speech": text,
                            "sprite": "-1",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        )
        ui.update_dialog("直播桥接测试", text, "#84C2D5", is_system=False)
        ui.post_llm_reply_finished()

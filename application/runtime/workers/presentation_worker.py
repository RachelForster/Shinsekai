"""Worker that presents dialog output and controls voice playback."""

import threading
from queue import Empty, Queue
from typing import Optional

import pygame

from application.chat.handlers.registry import default_presentation_handler_chain
from sdk.graph import Port
from sdk.logging import get_logger
from sdk.messages import PresentationMessage

from ..audio_playback_controller import (
    FrontendVoicePlaybackBackend,
    PlaybackState,
    PygameVoicePlaybackBackend,
    UnavailableVoicePlaybackBackend,
    VoicePlaybackController,
)
from ..context import get_app_runtime
from .base import ThreadDagNode

logger = get_logger(__name__)


class PresentationWorker(ThreadDagNode):
    PORT_PRESENTATION = "presentation"
    DIALOG_CHANNEL_ID = 7

    def __init__(
        self,
        input_queue: Queue[PresentationMessage] | None = None,
        parent=None,
        *,
        name: str = "ui_worker",
    ):
        super().__init__(name, parent=parent)
        self._app_inited = False
        self.presentation_queue = input_queue
        self.task_done_requested = threading.Event()
        self._dialog_active = False
        self.current_audio_path = None
        self.DIALOG_CHANNEL_ID = 7
        self.ui_out_dispatcher = default_presentation_handler_chain()
        if input_queue is not None:
            self.bind_input(self.PORT_PRESENTATION, input_queue)

    def _init_app(self):
        if self._app_inited:
            return
        rt = get_app_runtime()
        self.ui_update_manager = rt.ui_update_manager
        self.presentation_queue = self.inq(self.PORT_PRESENTATION)
        self._init_channel()
        br = get_app_runtime().ui_playback
        if (
            getattr(self.ui_update_manager, "audio_playback_owner", "backend")
            == "frontend"
        ):
            playback_backend = FrontendVoicePlaybackBackend(self.ui_update_manager)
        elif self.dialog_channel is not None:
            playback_backend = PygameVoicePlaybackBackend(
                channel=self.dialog_channel,
                sound_factory=pygame.mixer.Sound,
                ui_updates=self.ui_update_manager,
            )
        else:
            playback_backend = UnavailableVoicePlaybackBackend()
        self.playback_controller = VoicePlaybackController(
            playback_backend,
            interrupt_event=self.task_done_requested,
        )
        br.task_done_requested = self.task_done_requested
        br.dialog_channel = self.dialog_channel
        br.playback_controller = self.playback_controller
        self.ui_out_dispatcher.init_handlers()
        self._app_inited = True

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_PRESENTATION: Port(self.PORT_PRESENTATION)}

    def outputs(self) -> dict[str, Port]:
        return {}

    def _init_channel(self):
        if (
            getattr(self.ui_update_manager, "audio_playback_owner", "backend")
            == "frontend"
        ):
            self.dialog_channel = None
            print("UIWorker: React runtime delegates audio playback to the frontend.")
            return
        try:
            pygame.mixer.init()
            if pygame.mixer.get_num_channels() < self.DIALOG_CHANNEL_ID + 1:
                pygame.mixer.set_num_channels(self.DIALOG_CHANNEL_ID + 1)
            self.dialog_channel: pygame.mixer.Channel = pygame.mixer.Channel(
                self.DIALOG_CHANNEL_ID
            )
            print(
                f"PresentationWorker: 对话播放通道初始化成功，使用通道 {self.DIALOG_CHANNEL_ID}"
            )
        except Exception as e:
            print(f"PresentationWorker: Pygame Mixer 初始化或通道获取失败: {e}")
            self.dialog_channel = None

    def skip_speech(self):
        runtime = get_app_runtime()
        playback = runtime.ui_playback
        controller = getattr(playback, "playback_controller", None)
        if controller is not None:
            active_dialog = self._dialog_active
            if not controller.is_active() and not active_dialog:
                return
            controller.interrupt()
            self.current_audio_path = None
            playback.current_audio_path = None
            return
        current_audio_path = self.current_audio_path or getattr(
            playback, "current_audio_path", None
        )
        dialog_channel_busy = bool(
            self.dialog_channel and self.dialog_channel.get_busy()
        )
        active_dialog = self._dialog_active and not self.task_done_requested.is_set()
        audio_active = dialog_channel_busy or bool(current_audio_path)
        if not audio_active and not active_dialog:
            return
        if dialog_channel_busy:
            self.dialog_channel.stop()
        if audio_active:
            self.current_audio_path = None
            playback.current_audio_path = None
            ui_updates = (
                getattr(self, "ui_update_manager", None) or runtime.ui_update_manager
            )
            if hasattr(ui_updates, "post_tts_skip"):
                ui_updates.post_tts_skip()
        self.task_done_requested.set()

    @staticmethod
    def _queue_drained(queue) -> bool:
        unfinished = getattr(queue, "unfinished_tasks", None)
        if unfinished is not None:
            return int(unfinished) == 0
        return bool(queue.empty())

    def _finish_turn_if_drained(self, turn) -> bool:
        """Publish completion once every downstream result has been consumed."""
        rt = get_app_runtime()
        if turn.is_cancelled() or not turn.generation_complete.is_set():
            return False
        if not self._queue_drained(rt.dialog_queue) or not self._queue_drained(
            rt.presentation_queue
        ):
            return False
        controller = getattr(rt.ui_playback, "playback_controller", None)
        if controller is not None and controller.is_active():
            return False
        if self.dialog_channel is not None and self.dialog_channel.get_busy():
            return False
        if not rt.chat_turn_service.mark_idle(turn):
            return False
        self.ui_update_manager.post_llm_reply_finished()
        return True

    def run(self):
        self._init_app()
        idle_count = 0
        while self.running:
            output_data: Optional[PresentationMessage] = None
            turn = None
            got_item = False
            try:
                controller = getattr(
                    get_app_runtime().ui_playback,
                    "playback_controller",
                    None,
                )
                if controller is not None:
                    controller.prepare_next()
                else:
                    self.task_done_requested.clear()
                try:
                    output_data = self.presentation_queue.get(timeout=0.4)
                    got_item = True
                    idle_count = 0
                except Empty:
                    # Timeout — check if the full pipeline is now idle
                    idle_count += 1
                    if idle_count >= 1:
                        rt = get_app_runtime()
                        if rt.dialog_queue.empty() and rt.presentation_queue.empty():
                            controller = getattr(
                                rt.ui_playback, "playback_controller", None
                            )
                            busy = bool(
                                controller is not None and controller.is_active()
                            )
                            if not busy:
                                busy = (
                                    self.dialog_channel is not None
                                    and self.dialog_channel.get_busy()
                                )
                            if not busy:
                                self._finish_turn_if_drained(
                                    rt.chat_turn_service.current_turn()
                                )
                                idle_count = 0
                    continue

                if output_data is None:
                    break
                turn = get_app_runtime().chat_turn_service.current_turn()
                if turn.is_cancelled():
                    continue
                self._dialog_active = True
                self.ui_out_dispatcher.dispatch(output_data)
            except Exception as e:
                logger.exception(
                    "Presentation worker task failed",
                    extra={"event": "presentation.worker.failed"},
                )
                try:
                    self.ui_update_manager.post_notification(f"界面更新失败: {e}")
                except Exception:
                    pass
                if not self.task_done_requested.is_set():
                    _text = getattr(output_data, "text", "") or ""
                    wait = max(len(_text) / 10, 0.3) if _text else 0.3
                    self.task_done_requested.wait(timeout=wait)
            finally:
                self._dialog_active = False
                if got_item:
                    self.presentation_queue.task_done()
                if output_data is not None and turn is not None:
                    self._finish_turn_if_drained(turn)

    def stop(self):
        self.running = False
        controller = getattr(self, "playback_controller", None)
        if controller is not None:
            controller.shutdown()
        else:
            self.task_done_requested.set()
        self.presentation_queue.put(None)
        super().stop()

    def handle_playback_signal(
        self,
        playback_id: str,
        state: PlaybackState | str,
        error: str = "",
        *,
        renderer_id: str = "",
    ) -> bool:
        controller = getattr(self, "playback_controller", None)
        if controller is None:
            return False
        return controller.handle_signal(
            playback_id,
            state,
            error,
            renderer_id=renderer_id,
        )

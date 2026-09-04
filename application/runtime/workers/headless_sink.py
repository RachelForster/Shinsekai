"""Terminal worker that consumes dialog output without audio or UI."""

from queue import Queue
from typing import Optional

from sdk.graph import Port
from sdk.messages import TTSOutputMessage

from .base import ThreadDagNode


class HeadlessSinkNode(ThreadDagNode):
    """Consumes TTS output messages silently; no audio, no UI, no pygame.

    Intended as the terminal node in ``headless.yaml`` so that
    ``--headless`` mode avoids dragging in PresentationWorker / pygame audio channels.
    """

    PORT_TTS_OUTPUT = "tts_output"

    def __init__(
        self,
        input_queue: Queue[TTSOutputMessage] | None = None,
        parent=None,
        *,
        name: str = "headless_sink",
    ):
        super().__init__(name, parent=parent)
        self.audio_path_queue = input_queue
        if input_queue is not None:
            self.bind_input(self.PORT_TTS_OUTPUT, input_queue)

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_TTS_OUTPUT: Port(self.PORT_TTS_OUTPUT)}

    def outputs(self) -> dict[str, Port]:
        return {}

    def _init_app(self):
        if getattr(self, "_app_inited", False):
            return
        self.audio_path_queue = self.inq(self.PORT_TTS_OUTPUT)
        self._app_inited = True

    def run(self):
        self._init_app()
        while self.running:
            item: Optional[TTSOutputMessage] = None
            got_item = False
            try:
                item = self.audio_path_queue.get()
                got_item = True
                if item is None:
                    break
                if getattr(item, "text", ""):
                    print(f"[headless] {item.name}: {item.text}")
            except Exception:
                pass
            finally:
                if got_item:
                    self.audio_path_queue.task_done()

    def stop(self):
        self.running = False
        self.audio_path_queue.put(None)
        super().stop()

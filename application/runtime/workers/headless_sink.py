"""Terminal worker that consumes dialog output without audio or UI."""

from queue import Queue
from typing import Optional

from sdk.graph import Port
from sdk.messages import PresentationMessage

from .base import ThreadDagNode


class HeadlessSinkNode(ThreadDagNode):
    """Consumes presentation messages silently; no audio, no UI, no pygame.

    Intended as the terminal node in ``headless.yaml`` so that
    ``--headless`` mode avoids dragging in PresentationWorker / pygame audio channels.
    """

    PORT_PRESENTATION = "presentation"

    def __init__(
        self,
        input_queue: Queue[PresentationMessage] | None = None,
        parent=None,
        *,
        name: str = "headless_sink",
    ):
        super().__init__(name, parent=parent)
        self.presentation_queue = input_queue
        if input_queue is not None:
            self.bind_input(self.PORT_PRESENTATION, input_queue)

    def inputs(self) -> dict[str, Port]:
        return {self.PORT_PRESENTATION: Port(self.PORT_PRESENTATION)}

    def outputs(self) -> dict[str, Port]:
        return {}

    def _init_app(self):
        if getattr(self, "_app_inited", False):
            return
        self.presentation_queue = self.inq(self.PORT_PRESENTATION)
        self._app_inited = True

    def run(self):
        self._init_app()
        while self.running:
            item: Optional[PresentationMessage] = None
            got_item = False
            try:
                item = self.presentation_queue.get()
                got_item = True
                if item is None:
                    break
                if getattr(item, "text", ""):
                    print(f"[headless] {item.name}: {item.text}")
            except Exception:
                pass
            finally:
                if got_item:
                    self.presentation_queue.task_done()

    def stop(self):
        self.running = False
        self.presentation_queue.put(None)
        super().stop()

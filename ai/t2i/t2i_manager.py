"""T2I generation queue manager and compatibility factory wrapper."""

from __future__ import annotations

from pathlib import Path
import queue
import threading
from typing import Any, Dict, Optional

from ai.t2i.registry import create_t2i_adapter, get_t2i_adapter_registry
from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter  # noqa: F401
from sdk.adapters.t2i import T2IAdapter


class T2IAdapterFactory:
    """Compatibility wrapper backed by the process-wide T2I ``AdapterRegistry``."""

    _adapters = get_t2i_adapter_registry().as_mutable_mapping()

    @staticmethod
    def create_adapter(adapter_name: str, **kwargs: Any) -> T2IAdapter:
        """Create and return a ``T2IAdapter`` instance for ``adapter_name``."""
        return create_t2i_adapter(adapter_name, **kwargs)


class T2IManager:
    """Manage queued text-to-image synthesis and circular disk caching."""

    def __init__(
        self,
        t2i_adapter: Optional[T2IAdapter],
        image_cache_dir: str = ".\\cache\\images",
    ) -> None:
        self.image_cache_dir = Path(image_cache_dir)
        self.cache_num = 10
        self.index = 0

        self.image_cache_dir.mkdir(exist_ok=True, parents=True)
        self.t2i_adapter: Optional[T2IAdapter] = t2i_adapter

        self.task_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def set_t2i_adapter(self, adapter: T2IAdapter) -> None:
        """Allow switching the T2I adapter at runtime."""
        self.t2i_adapter = adapter

    def t2i(
        self,
        prompt: str,
        prompt_processor: Optional[Any] = None,
        *,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """Generate an image using the active adapter and return the saved file path."""
        if not self.t2i_adapter:
            print("Error: T2I adapter is not set.")
            return None

        print(f"Generating image for prompt: '{prompt[:50]}...'")

        destination = (
            Path(file_path)
            if file_path
            else self.image_cache_dir / f"{self.index % self.cache_num}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.index += 1

        return self.t2i_adapter.generate_image(
            prompt=prompt,
            file_path=destination.as_posix(),
            **kwargs,
        )

    def switch_model(self, model_info: Dict[str, Any]) -> None:
        """Switch the T2I model/configuration via the active adapter."""
        if self.t2i_adapter:
            self.t2i_adapter.switch_model(model_info)
        else:
            print("Error: Cannot switch model, T2I adapter is not set.")

    def _process_queue(self) -> None:
        """Worker thread to process T2I generation tasks sequentially."""
        while True:
            task = self.task_queue.get()
            if task is None:
                break
            try:
                if task["type"] == "generate":
                    self.t2i(
                        task["prompt"], task["prompt_processor"], **task["kwargs"]
                    )
            except Exception as exc:
                print(f"T2I task failed: {exc}")
            finally:
                self.task_queue.task_done()

    def queue_generation(
        self,
        prompt: str,
        prompt_processor: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Enqueue a T2I generation request."""
        self.task_queue.put(
            {
                "type": "generate",
                "prompt": prompt,
                "prompt_processor": prompt_processor,
                "kwargs": kwargs,
            }
        )

    def shutdown(self, *, stop_server: bool = False) -> None:
        """Shut down the queue and worker thread."""
        print("Shutting down T2IManager worker thread...")
        self.task_queue.put(None)
        self.worker_thread.join()
        if stop_server and self.t2i_adapter is not None:
            stop_fn = getattr(self.t2i_adapter, "stop_server", None)
            if callable(stop_fn):
                stop_fn()

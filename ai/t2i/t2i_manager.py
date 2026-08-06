import requests
import threading
import queue
import os
from typing import Optional, Dict, Any

from core.paths import (
    project_root as runtime_project_root,
    require_directory_without_links,
    resolve_project_output_path,
    resolve_project_path,
)
from sdk.adapters.t2i import T2IAdapter
from ai.t2i.t2i_adapter import ComfyUIT2IAdapter, StableDiffusionAdapter

class T2IAdapterFactory:
    """
    Factory for creating different T2IAdapter instances.
    """
    _adapters = {
        'stable diffusion': StableDiffusionAdapter,
        'comfyui': ComfyUIT2IAdapter,
    }

    @staticmethod
    def create_adapter(adapter_name: str, **kwargs) -> T2IAdapter:
        """
        Creates and returns a T2IAdapter instance based on the given name.

        Args:
            adapter_name (str): The name of the adapter to create (e.g., 'stable-diffusion').
            **kwargs: Configuration arguments for the adapter's constructor (e.g., api_key, api_url).

        Returns:
            T2IAdapter: An instance of a concrete T2IAdapter.

        Raises:
            ValueError: If the adapter name is not supported.
        """
        adapter_class = T2IAdapterFactory._adapters.get(adapter_name.lower())

        if not adapter_class:
            raise ValueError(f"Unsupported T2I adapter: '{adapter_name}'. Supported adapters are: {list(T2IAdapterFactory._adapters.keys())}")

        try:
            # Instantiate the correct adapter class with the provided kwargs
            from config.adapter_extra_kwargs import filter_kwargs_for_ctor

            return adapter_class(
                **filter_kwargs_for_ctor(adapter_class, kwargs)
            )
        except TypeError as e:
            print(f"Error creating adapter '{adapter_name}'. Check the required arguments for {adapter_name}.")
            raise e

# T2I管理器
class T2IManager:
    def __init__(
        self,
        t2i_adapter,
        image_cache_dir: str | os.PathLike[str] | None = None,
        *,
        project_root: str | os.PathLike[str] | None = None,
    ):
        root = runtime_project_root() if project_root is None else resolve_project_path(
            ".",
            root=project_root,
        )

        raw_cache = os.fspath(
            "data/cache/images" if image_cache_dir is None else image_cache_dir
        )
        self.image_cache_dir = resolve_project_output_path(raw_cache, root=root)
        self.cache_num = 10  # Max number of cached images
        self.index = 0       # Index for circular caching

        self.image_cache_dir.mkdir(exist_ok=True, parents=True)
        self.image_cache_dir = require_directory_without_links(
            self.image_cache_dir,
            field="T2I image cache directory",
        )
        # Use the adapter for T2I operations
        self.t2i_adapter: Optional[T2IAdapter] = t2i_adapter

        # Work queue for processing image generation requests
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def set_t2i_adapter(self, adapter: T2IAdapter):
        """Allows switching the T2I adapter at runtime."""
        self.t2i_adapter = adapter

    def t2i(self, prompt: str, prompt_processor: Optional[Any] = None, **kwargs) -> Optional[str]:
        """
        Generates T2I image using the currently set adapter and returns the file path.
        """
        if not self.t2i_adapter:
            print("Error: T2I adapter is not set.")
            return None

        print(f"Generating image for prompt: '{prompt[:50]}...'")


        # Determine the file path for caching
        file_path = self.image_cache_dir / f'{self.index % self.cache_num}.png'
        self.index += 1

        # The adapter handles the specifics of the image generation
        return self.t2i_adapter.generate_image(
            prompt=prompt,
            file_path=file_path.as_posix(),
            **kwargs
        )

    def switch_model(self, model_info: Dict[str, Any]):
        """Switches the T2I model/configuration via the adapter."""
        if self.t2i_adapter:
            self.t2i_adapter.switch_model(model_info)
        else:
            print("Error: Cannot switch model, T2I adapter is not set.")

    def _process_queue(self):
        """Worker thread to process T2I generation tasks in the queue sequentially."""
        while True:
            task = self.task_queue.get()
            if task is None:  # Termination signal
                break
            try:
                if task['type'] == 'generate':
                    self.t2i(task['prompt'], task['prompt_processor'], **task['kwargs'])
                # Add other task types (e.g., 'inpaint', 'upscale') here
            except Exception as e:
                print(f"T2I task failed: {e}")
            finally:
                self.task_queue.task_done()

    def queue_generation(self, prompt: str, prompt_processor: Optional[Any] = None, **kwargs):
        """Adds a T2I generation request to the queue."""
        self.task_queue.put({
            'type': 'generate',
            'prompt': prompt,
            'prompt_processor': prompt_processor,
            'kwargs': kwargs
        })

    def shutdown(self):
        """Shuts down the queue and worker thread."""
        print("Shutting down T2IManager worker thread...")
        self.task_queue.put(None)
        self.worker_thread.join()

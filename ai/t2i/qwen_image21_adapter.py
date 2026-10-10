"""Lazy, isolated local Qwen-Image-2.1 inference; no ML imports in the host."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout as FileLockTimeout

from core.model_assets.service import find_cached_huggingface_snapshot
from sdk.adapters.t2i import T2IAdapter

from .qwen_image21_assets import QWEN_IMAGE21_MODEL_ASSET, complete_qwen_snapshot


class QwenImage21Adapter(T2IAdapter):
    def __init__(
        self,
        python_executable: str = "",
        dependency_path: str = "",
        model_path: str = "",
        transformer_bits: int = 8,
        resolution: int = 768,
        steps: int = 40,
        seed: int = 42,
        timeout_seconds: int = 1800,
    ) -> None:
        self.python_executable = python_executable
        self.dependency_path = dependency_path
        self.model_path = model_path
        self.transformer_bits = int(transformer_bits)
        self.resolution = int(resolution)
        self.steps = int(steps)
        self.seed = int(seed)
        self.timeout_seconds = int(timeout_seconds)
        if self.transformer_bits not in (4, 8):
            raise ValueError("transformer_bits must be 4 or 8")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._state_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._closed = False
        self._shutdown_event = threading.Event()

    @staticmethod
    def get_config_schema() -> dict[str, Any]:
        return {
            "python_executable": {
                "type": "str",
                "label": "Python executable (isolated Qwen environment)",
                "default": "",
            },
            "dependency_path": {
                "type": "str",
                "label": "Optional isolated site-packages directory",
                "default": "",
            },
            "model_path": {
                "type": "str",
                "label": "Local model directory (empty: managed model cache)",
                "default": "",
            },
            "transformer_bits": {
                "type": "int",
                "label": "Transformer quantization bits",
                "default": 8,
                "choices": ["4", "8"],
            },
            "resolution": {
                "type": "int",
                "label": "Output resolution / reference encoding resolution",
                "default": 768,
                "min": 256,
                "max": 2048,
            },
            "steps": {
                "type": "int",
                "label": "Inference steps",
                "default": 40,
                "min": 1,
                "max": 100,
            },
            "seed": {"type": "int", "label": "Seed (-1: random)", "default": 42},
            "timeout_seconds": {
                "type": "int",
                "label": "Generation timeout (seconds)",
                "default": 1800,
                "min": 1,
            },
        }

    def generate_image(
        self,
        prompt: str,
        file_path: str | None = None,
        *,
        reference_images: Sequence[str | Path] | None = None,
        **kwargs: Any,
    ) -> str:
        references = [
            Path(path).expanduser().resolve()
            for path in self.normalize_reference_images(reference_images)
        ]
        if len(references) > 10:
            raise ValueError("Qwen-Image-2.1 accepts at most 10 reference images")
        if any(not path.is_file() for path in references):
            raise ValueError("reference_images must point to existing local files")
        output = (
            Path(
                file_path
                or Path(tempfile.gettempdir()) / f"qwen-{uuid.uuid4().hex}.png"
            )
            .expanduser()
            .resolve()
        )
        if output in references:
            raise ValueError("Output must differ from every reference image")
        if output.suffix.lower() != ".png":
            raise ValueError("Qwen output must use a .png extension to preserve RGBA")
        model = (
            Path(self.model_path).expanduser().resolve()
            if self.model_path
            else find_cached_huggingface_snapshot(QWEN_IMAGE21_MODEL_ASSET)
        )
        if model is None or not complete_qwen_snapshot(model):
            raise RuntimeError(
                "Qwen-Image-2.1 model is missing or incomplete. Download it in AI services > Image generation, or configure a complete local model directory."
            )
        if self.python_executable:
            python = str(Path(self.python_executable).expanduser().resolve())
        else:
            from plugin_system.requirements.install import pip_python_executable

            python = str(pip_python_executable())
        request = {
            "prompt": str(prompt),
            "output": str(output),
            "model_path": str(model),
            "reference_images": [str(path) for path in references],
            "dependency_path": (
                str(Path(self.dependency_path).expanduser().resolve())
                if self.dependency_path
                else ""
            ),
            "transformer_bits": self.transformer_bits,
            "resolution": int(kwargs.get("resolution", self.resolution)),
            "steps": int(kwargs.get("steps", self.steps)),
            "seed": int(kwargs.get("seed", self.seed)),
            "transparent": bool(kwargs.get("transparent", False)),
        }
        canvas_index = kwargs.get("reference_canvas_index")
        if canvas_index is not None:
            if (
                isinstance(canvas_index, bool)
                or not isinstance(canvas_index, int)
                or not 0 <= canvas_index < len(references)
            ):
                raise ValueError(
                    "reference_canvas_index must identify a reference image"
                )
            request["reference_canvas_index"] = canvas_index
        for dimension in ("width", "height"):
            if kwargs.get(dimension) is not None:
                request[dimension] = int(kwargs[dimension])
                if request[dimension] < 32 or request[dimension] % 32:
                    raise ValueError(f"{dimension} must be a positive multiple of 32")
        if not 256 <= request["resolution"] <= 2048 or not 1 <= request["steps"] <= 100:
            raise ValueError("resolution must be 256..2048; steps must be 1..100")
        with self._generation_slot(kwargs.get("on_progress")):
            return self._run_worker(python, request, kwargs.get("on_progress"))

    @contextmanager
    def _generation_slot(self, on_progress: Any):
        # Chat and the bridge run in different processes. Use the same temporary
        # directory convention as the TTS model-session lock.
        directory = Path(tempfile.gettempdir()) / "shinsekai-t2i-locks"
        directory.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(directory / "qwen-image21-cuda.lock"))
        deadline = time.monotonic() + self.timeout_seconds
        reported = False
        while True:
            if self._closed:
                raise RuntimeError("Qwen adapter has been shut down")
            try:
                lock.acquire(timeout=0)
                break
            except FileLockTimeout:
                if not reported and callable(on_progress):
                    on_progress(0, "Waiting for another Qwen generation to finish")
                reported = True
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for another Qwen generation")
                self._shutdown_event.wait(0.1)
        try:
            yield
        finally:
            lock.release()

    def _run_worker(
        self, python: str, request: dict[str, Any], on_progress: Any
    ) -> str:
        env = os.environ.copy()
        env.update(
            PYTHONIOENCODING="utf-8",
            PYTHONUNBUFFERED="1",
            TOKENIZERS_PARALLELISM="false",
            HF_HUB_OFFLINE="1",
        )
        # Pass source as code so frozen releases need no separately bundled .py.
        from .qwen_image21_worker import WORKER_SOURCE

        with self._state_lock:
            if self._closed:
                raise RuntimeError("Qwen adapter has been shut down")
            process = subprocess.Popen(
                [python, "-u", "-c", WORKER_SOURCE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._process = process
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        stderr: deque[str] = deque(maxlen=32)

        def read_stdout() -> None:
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.put(event)
                    except ValueError:
                        pass
            finally:
                events.put(None)

        def read_stderr() -> None:
            for line in process.stderr:
                stderr.append(line[-2048:])

        readers = [
            threading.Thread(target=read_stdout, daemon=True),
            threading.Thread(target=read_stderr, daemon=True),
        ]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + self.timeout_seconds
        result = None
        error = ""
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False))
            process.stdin.close()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Qwen generation exceeded {self.timeout_seconds} seconds"
                    )
                try:
                    event = events.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    continue
                if event is None:
                    break
                if event.get("type") == "result":
                    result = event.get("path")
                elif event.get("type") == "error":
                    error = str(event.get("message", ""))
                elif event.get("type") == "progress" and callable(on_progress):
                    on_progress(
                        float(event.get("progress", 0)), str(event.get("message", ""))
                    )
            status = process.wait(timeout=max(0.01, deadline - time.monotonic()))
            if status != 0 or error:
                raise RuntimeError(
                    f"Qwen generation failed: {error or ''.join(stderr)[-8192:] or f'worker exited with status {status}'}"
                )
            if result != request["output"] or not Path(result).is_file():
                raise RuntimeError("Qwen worker returned no output image")
            return result
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            with self._state_lock:
                self._process = None

    def switch_model(self, model_info: dict[str, Any]) -> None:
        if "model_path" in model_info:
            self.model_path = str(model_info["model_path"] or "")

    def shutdown(self) -> None:
        with self._state_lock:
            self._closed = True
            self._shutdown_event.set()
            if self._process is not None and self._process.poll() is None:
                self._process.kill()

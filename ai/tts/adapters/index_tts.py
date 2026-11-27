"""IndexTTS HTTP service adapter."""

from __future__ import annotations

import os
from typing import Any

import requests

from ai.tts.adapters.local_http import LocalHttpTTSAdapter, is_local_server_url
from ai.tts.server_process import start_server_process
from core.adapters import builtin_adapter
from sdk.logging import get_logger

logger = get_logger(__name__)


@builtin_adapter("index-tts", label="IndexTTS", order=50)
class IndexTTSAdapter(LocalHttpTTSAdapter):
    """Adapter for an IndexTTS HTTP synthesis server."""

    SERVICE_NAME = "IndexTTS"

    def __init__(
        self,
        index_server_url: str = "http://localhost:9880/",
        index_server_work_path: str | None = None,
        tts_server_url: str | None = None,
        gpt_sovits_work_path: str | None = None,
    ) -> None:
        self.index_server_url = self._init_http_runtime(
            tts_server_url or index_server_url
        )
        self.current_model: str | None = None
        self.gpt_sovits_work_path = (
            str(index_server_work_path or gpt_sovits_work_path or "").strip() or None
        )
        self._start_server_process()

    def _server_is_reachable(self) -> bool:
        try:
            response = self._session.get(self.index_server_url, timeout=5)
            return response.status_code < 500
        except requests.RequestException:
            return False

    def _is_local_server_url(self) -> bool:
        return is_local_server_url(self.index_server_url)

    def _start_server_process(self) -> None:
        """Start the local IndexTTS server process if not already reachable."""
        if self._server_is_reachable():
            logger.info("IndexTTS server is already running.")
            return
        if not self._is_local_server_url():
            logger.info("Remote IndexTTS server is not reachable; skip local auto-start.")
            return
        logger.info("IndexTTS server not found, attempting to start...")

        if not self.gpt_sovits_work_path:
            raise RuntimeError(
                "Local IndexTTS server is not reachable; set the IndexTTS startup path."
            )

        os_path = self.gpt_sovits_work_path
        embedded_python_path = os.path.join(os_path, "runtime", "python.exe")
        api_path = os.path.join(os_path, "api_v2.py")
        if not os.path.isfile(api_path):
            raise FileNotFoundError(f"IndexTTS api_v2.py not found: {api_path}")

        self._server_process = start_server_process(
            embedded_python_path, api_path, cwd=os_path
        )
        logger.info("IndexTTS server starting...")

    def generate_speech(self, text: str, file_path: str | None = None, **kwargs: Any) -> str | None:
        """Generate speech using the IndexTTS HTTP API."""
        try:
            params = {
                "text": text,
                "model_id": self.current_model,
                "voice_name": kwargs.get("voice_name", "default"),
                "language": kwargs.get("text_lang", "ja"),
            }
            response = self._session.post(
                self.index_server_url + "generate", json=params
            )
            response.raise_for_status()

            target_path = file_path or "path_to_index_tts_file.wav"
            with open(target_path, "wb") as handle:
                handle.write(response.content)

            return os.path.abspath(target_path)
        except Exception as exc:
            logger.error("IndexTTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        """Switch the active model identifier for IndexTTS."""
        model_id = (model_info or {}).get("model_id")
        if model_id and self.current_model != model_id:
            logger.info("Switching to IndexTTS model: %s", model_id)
            self.current_model = model_id

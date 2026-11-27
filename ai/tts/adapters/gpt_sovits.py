"""GPT-SoVITS local/remote HTTP TTS adapter and pretrained weight resolution."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

import requests

from ai.tts.adapters.local_http import (
    LocalHttpTTSAdapter,
    format_http_error,
    is_local_server_url,
)
from ai.tts.server_process import server_python, start_server_process
from sdk.logging import get_logger

logger = get_logger(__name__)

PRETRAINED_MODEL_CANDIDATES: tuple[tuple[str, str], ...] = (
    (
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
    ),
    (
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
    ),
    (
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/gsv-v4-pretrained/s2v4.pth",
    ),
    (
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/s2Gv3.pth",
    ),
    (
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    ),
    (
        "GPT_SoVITS/pretrained_models/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt",
        "GPT_SoVITS/pretrained_models/s2G488k.pth",
    ),
)


def resolve_pretrained_base_models(work_path: str | Path | None) -> tuple[str, str]:
    """Return installed local pretrained ``(gpt_ckpt, sovits_pth)`` paths for zero-shot fallback."""
    raw = str(work_path or "").strip()
    if not raw:
        return "", ""
    root = Path(raw)
    if root.suffix.lower() == ".py":
        root = root.parent
    if not root.is_dir():
        return "", ""

    for rel_gpt, rel_sovits in PRETRAINED_MODEL_CANDIDATES:
        gpt_file = root / rel_gpt
        sovits_file = root / rel_sovits
        if gpt_file.is_file() and sovits_file.is_file():
            return gpt_file.resolve().as_posix(), sovits_file.resolve().as_posix()

    return "", ""


class GPTSoVitsAdapter(LocalHttpTTSAdapter):
    """Adapter for the GPT-SoVITS HTTP v2 TTS service."""

    SERVICE_NAME = "GPT-SoVITS"

    def __init__(
        self,
        tts_server_url: str = "http://127.0.0.1:9880/",
        gpt_sovits_work_path: str | None = None,
    ) -> None:
        self.tts_server_url = self._init_http_runtime(tts_server_url)
        self.sovits_model_path: str | None = None
        self.gpt_model_path: str | None = None
        self.gpt_sovits_work_path = str(gpt_sovits_work_path or "").strip() or None

        # Normalize when the user pointed directly to api_v2.py.
        if self.gpt_sovits_work_path and self.gpt_sovits_work_path.endswith(".py"):
            self.gpt_sovits_work_path = Path(self.gpt_sovits_work_path).parent.as_posix()

        self._start_server_process()

    def _server_is_reachable(self) -> bool:
        try:
            response = self._session.get(self.tts_server_url, timeout=5)
            if response.status_code < 500:
                return True
        except requests.RequestException:
            pass

        try:
            response = self._session.get(self.tts_server_url + "docs", timeout=5)
            return response.status_code < 500
        except requests.RequestException:
            return False

    def _is_local_server_url(self) -> bool:
        return is_local_server_url(self.tts_server_url)

    @staticmethod
    def _response_error_text(response: Any, action: str) -> str:
        return format_http_error(response, action)

    def _start_server_process(self) -> None:
        """Start the local GPT-SoVITS server process if it is not already running."""
        if self._server_is_reachable():
            logger.info("GPT-SoVITS server is already reachable.")
            return

        if not self._is_local_server_url():
            logger.info("Remote GPT-SoVITS server is not reachable; skip local auto-start.")
            return

        if not self.gpt_sovits_work_path:
            raise RuntimeError(
                "Local GPT-SoVITS server is not reachable; set the GPT-SoVITS startup path."
            )

        os_path = Path(self.gpt_sovits_work_path)
        api_path = os_path / "api_v2.py"
        if not api_path.is_file():
            raise FileNotFoundError(f"GPT-SoVITS api_v2.py not found: {api_path}")

        bundled_python = server_python(
            os_path / "runtime" / ("python.exe" if os.name == "nt" else "python")
        )
        python_path = bundled_python if bundled_python.exists() else Path(sys.executable)
        self._server_process = start_server_process(python_path, api_path, cwd=os_path)
        logger.info("GPT-SoVITS server starting...")

    def generate_speech(self, text: str, file_path: str | None = None, **kwargs: Any) -> str | None:
        """Generate TTS audio via GPT-SoVITS ``/tts`` and write to ``file_path``."""
        speed_factor = kwargs.get("speed_factor")
        if speed_factor is None:
            speed_factor = 1.0
        try:
            batch_size = max(1, int(kwargs.get("batch_size", 1)))
        except (TypeError, ValueError):
            batch_size = 1

        params: dict[str, Any] = {
            "ref_audio_path": kwargs.get("ref_audio_path", ""),
            "prompt_text": kwargs.get("prompt_text", ""),
            "prompt_lang": kwargs.get("prompt_lang", ""),
            "text": text,
            "text_lang": kwargs.get("text_lang", "ja"),
            "text_split_method": kwargs.get("text_split_method", "cut5"),
            "batch_size": batch_size,
            "speed_factor": speed_factor,
        }
        for key in (
            "batch_threshold",
            "split_bucket",
            "parallel_infer",
            "super_sampling",
            "sample_steps",
            "streaming_mode",
            "media_type",
        ):
            if key in kwargs and kwargs[key] is not None:
                params[key] = kwargs[key]

        try:
            response = self._session.post(
                self.tts_server_url + "tts", json=params, timeout=300
            )
            if not response.ok:
                raise RuntimeError(self._response_error_text(response, "TTS request"))

            target_path = file_path or "path_to_temporary_file.wav"
            with open(target_path, "wb") as handle:
                handle.write(response.content)

            return os.path.abspath(target_path)
        except Exception as exc:
            logger.error("GPT-SoVITS TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        """Switch GPT and SoVITS weights, resetting to pretrained base weights on zero-shot."""
        model_info = model_info or {}
        gpt_model_path = str(model_info.get("gpt_model_path") or "").strip()
        sovits_model_path = str(model_info.get("sovits_model_path") or "").strip()

        if (
            (not gpt_model_path or not sovits_model_path)
            and self._is_local_server_url()
            and getattr(self, "gpt_sovits_work_path", None)
        ):
            base_gpt, base_sovits = resolve_pretrained_base_models(self.gpt_sovits_work_path)
            if not gpt_model_path and base_gpt:
                gpt_model_path = base_gpt
            if not sovits_model_path and base_sovits:
                sovits_model_path = base_sovits

        if (
            self.sovits_model_path == sovits_model_path
            and self.gpt_model_path == gpt_model_path
        ):
            logger.debug(
                "No GPT-SoVITS model switch needed (%s, %s)",
                self.gpt_model_path,
                self.sovits_model_path,
            )
            return

        try:
            if gpt_model_path and gpt_model_path.lower().endswith(".ckpt"):
                if self.gpt_model_path != gpt_model_path:
                    response = self._session.get(
                        self.tts_server_url + "set_gpt_weights",
                        params={"weights_path": gpt_model_path},
                        timeout=180,
                    )
                    if not response.ok:
                        raise RuntimeError(
                            self._response_error_text(response, "GPT weight switch")
                        )
                    self.gpt_model_path = gpt_model_path
                    logger.info("GPT model switched successfully: %s", gpt_model_path)
            elif not gpt_model_path and self.gpt_model_path is None:
                self.gpt_model_path = ""
        except Exception as exc:
            logger.error("Failed to switch GPT model: %s", exc)
            raise

        try:
            if sovits_model_path and sovits_model_path.lower().endswith(".pth"):
                if self.sovits_model_path != sovits_model_path:
                    response = self._session.get(
                        self.tts_server_url + "set_sovits_weights",
                        params={"weights_path": sovits_model_path},
                        timeout=180,
                    )
                    if not response.ok:
                        raise RuntimeError(
                            self._response_error_text(response, "SoVITS weight switch")
                        )
                    self.sovits_model_path = sovits_model_path
                    logger.info("SoVITS model switched successfully: %s", sovits_model_path)
            elif not sovits_model_path and self.sovits_model_path is None:
                self.sovits_model_path = ""
        except Exception as exc:
            logger.error("Failed to switch SoVITS model: %s", exc)
            raise

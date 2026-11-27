"""Genie TTS adapter with ONNX conversion, PCM-to-WAV framing, and process management."""

from __future__ import annotations

import array
import base64
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import wave

from ai.tts.adapters.local_http import LocalHttpTTSAdapter
from ai.tts.server_process import server_python, start_server_process
from sdk.logging import get_logger

logger = get_logger(__name__)


class GenieTTSAdapter(LocalHttpTTSAdapter):
    """Adapter for the Genie TTS HTTP service."""

    SERVICE_NAME = "Genie TTS"

    def __init__(
        self,
        tts_server_url: str = "http://127.0.0.1:9880/",
        tts_work_path: str | None = None,
        gpt_sovits_work_path: str | None = None,
    ) -> None:
        self.tts_server_url = self._init_http_runtime(tts_server_url)
        # Keep compatibility with existing factory argument name.
        self.tts_work_path = str(tts_work_path or gpt_sovits_work_path or "").strip() or None
        self.character_name: str | None = None
        self.onnx_model_dir: str | None = None
        self.loaded_character_name: str | None = None
        self.reference_audio_key: str | None = None
        self._start_server_process()

    @staticmethod
    def _encode_name(name: str) -> str:
        if not name:
            return ""
        # Remove '=' padding to keep folder names shorter and cleaner.
        return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")

    def _resolve_converter_script(self) -> Path | None:
        if not self.tts_work_path:
            return None
        base_path = Path(self.tts_work_path)
        if base_path.suffix.lower() == ".py":
            return base_path if base_path.exists() else None
        for script in (base_path / "convert.py", base_path / "convery.py"):
            if script.exists():
                return script
        return None

    def _has_onnx_files(self, onnx_dir: str) -> bool:
        if not onnx_dir:
            return False
        onnx_path = Path(onnx_dir)
        if not onnx_path.exists() or not onnx_path.is_dir():
            return False
        return any(p.suffix.lower() == ".onnx" for p in onnx_path.glob("*.onnx"))

    def _convert_model_to_onnx(
        self,
        character_name: str,
        ckpt_model_path: str,
        pth_model_path: str,
        onnx_dir: str,
    ) -> None:
        converter_script = self._resolve_converter_script()
        if converter_script is None:
            raise FileNotFoundError("Cannot find convert.py/convery.py in tts_work_path.")

        work_path = converter_script.parent
        embedded_python_path = work_path / "runtime" / "python.exe"
        if not embedded_python_path.exists():
            raise FileNotFoundError(f"Runtime python not found: {embedded_python_path}")

        Path(onnx_dir).mkdir(parents=True, exist_ok=True)
        cmd = [
            str(embedded_python_path),
            str(converter_script),
            "--pth",
            pth_model_path,
            "--ckpt",
            ckpt_model_path,
            "--out",
            onnx_dir,
        ]
        logger.info("Converting ONNX for %r...", character_name)
        result = subprocess.run(
            cmd,
            cwd=str(work_path),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Convert failed (code={result.returncode}).\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        logger.info("ONNX convert finished for %r: %s", character_name, onnx_dir)

    def _is_valid_wav_file(self, file_path: str) -> bool:
        if not file_path or not os.path.exists(file_path):
            return False
        try:
            with wave.open(file_path, "rb") as wav_f:
                wav_f.getnchannels()
                wav_f.getframerate()
                wav_f.getnframes()
            return True
        except Exception:
            return False

    def _write_raw_stream_as_wav(
        self, raw_bytes: bytes, out_path: str, sample_rate: int = 32000
    ) -> bool:
        if not raw_bytes:
            return False
        pcm_bytes = b""

        # Case 1: float32 PCM in [-1, 1]
        if len(raw_bytes) % 4 == 0:
            try:
                float_arr = array.array("f")
                float_arr.frombytes(raw_bytes)
                if float_arr:
                    max_abs = max(abs(x) for x in float_arr if math.isfinite(x))
                    if max_abs <= 2.0:
                        pcm_i16 = array.array("h")
                        for sample in float_arr:
                            if not math.isfinite(sample):
                                sample = 0.0
                            sample = max(-1.0, min(1.0, sample))
                            pcm_i16.append(int(sample * 32767.0))
                        pcm_bytes = pcm_i16.tobytes()
            except Exception:
                pcm_bytes = b""

        # Case 2: int16 PCM stream
        if not pcm_bytes and len(raw_bytes) % 2 == 0:
            pcm_bytes = raw_bytes

        if not pcm_bytes:
            return False

        try:
            with wave.open(out_path, "wb") as wav_f:
                wav_f.setnchannels(1)
                wav_f.setsampwidth(2)
                wav_f.setframerate(sample_rate)
                wav_f.writeframes(pcm_bytes)
            return self._is_valid_wav_file(out_path)
        except Exception:
            return False

    def _write_pcm_chunks_as_wav(
        self, chunks: list[bytes], out_path: str, sample_rate: int = 32000
    ) -> bool:
        try:
            with wave.open(out_path, "wb") as wav_f:
                wav_f.setnchannels(1)
                wav_f.setsampwidth(2)
                wav_f.setframerate(sample_rate)
                for chunk in chunks:
                    if chunk:
                        wav_f.writeframesraw(chunk)
            return self._is_valid_wav_file(out_path)
        except Exception:
            return False

    def _start_server_process(self) -> None:
        """Start the Genie TTS server process if it isn't running."""
        if self._is_server_alive():
            logger.info("Genie TTS server is already running.")
            return

        if not self.tts_work_path:
            raise RuntimeError(
                "Local Genie TTS server is not reachable; set the Genie TTS startup path."
            )

        os_path = self.tts_work_path
        if os_path.endswith(".py"):
            os_path = str(Path(os_path).parent)

        embedded_python_path = server_python(Path(os_path) / "runtime" / "python.exe")
        start_script_path = os.path.join(os_path, "start.py")

        if not os.path.exists(embedded_python_path):
            logger.warning("Genie TTS runtime not found: %s", embedded_python_path)
            return
        if not os.path.exists(start_script_path):
            logger.warning("Genie TTS start.py not found: %s", start_script_path)
            return

        self._server_process = start_server_process(
            embedded_python_path, start_script_path, cwd=os_path
        )
        logger.info("Genie TTS server starting...")
        for _ in range(20):
            time.sleep(0.5)
            if self._is_server_alive():
                logger.info("Genie TTS server started successfully.")
                return
        logger.warning("Genie TTS server start timeout, continue and retry on request.")

    def _is_server_alive(self) -> bool:
        try:
            response = self._http_client().post(self.tts_server_url + "stop", timeout=1.5)
            return response.status_code in (200, 204, 405)
        except Exception:
            return False

    def _server_is_reachable(self) -> bool:
        return self._is_server_alive()

    def _load_character_model(self, language: str = "ja") -> None:
        """Load the character model via Genie TTS HTTP API."""
        if not self.character_name or not self.onnx_model_dir:
            logger.warning("Genie TTS switch_model missing character_name/onnx_model_dir.")
            return
        try:
            encoded_character_name = self._encode_name(self.character_name)
            payload = {
                "character_name": encoded_character_name,
                "onnx_model_dir": self.onnx_model_dir,
                "language": language,
            }
            response = self._http_client().post(
                self.tts_server_url + "load_character", json=payload, timeout=20
            )
            response.raise_for_status()
            self.loaded_character_name = self.character_name
            logger.info("Genie TTS character %r loaded successfully.", self.character_name)
        except Exception as exc:
            logger.error("Failed to load Genie TTS character model: %s", exc)
            raise

    def generate_speech(self, text: str, file_path: str | None = None, **kwargs: Any) -> str | None:
        """Generate TTS audio using the Genie TTS engine."""
        runtime_character_name = kwargs.get("character_name")
        if runtime_character_name and runtime_character_name != self.character_name:
            self.character_name = runtime_character_name

        if not self.character_name:
            logger.warning("Genie TTS has no active character. Call switch_model first.")
            return None

        ref_audio_path = kwargs.get("ref_audio_path")
        audio_text = kwargs.get("prompt_text")
        audio_lang = kwargs.get("prompt_lang") or kwargs.get("text_lang") or "zh"
        reference_audio_key = f"{ref_audio_path}|{audio_text}|{audio_lang}"
        encoded_character_name = self._encode_name(self.character_name)

        if self.loaded_character_name != self.character_name:
            self._load_character_model(audio_lang)

        if ref_audio_path and audio_text and self.reference_audio_key != reference_audio_key:
            try:
                payload = {
                    "character_name": encoded_character_name,
                    "audio_path": ref_audio_path,
                    "audio_text": audio_text,
                    "language": audio_lang,
                }
                response = self._http_client().post(
                    self.tts_server_url + "set_reference_audio", json=payload, timeout=20
                )
                response.raise_for_status()
                self.reference_audio_key = reference_audio_key
            except Exception as exc:
                logger.warning("Failed to set Genie TTS reference audio: %s", exc)

        try:
            target_path = file_path or str(
                Path(tempfile.gettempdir()) / f"genie_tts_{os.urandom(4).hex()}.wav"
            )
            abs_file_path = os.path.abspath(target_path)
            os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
            payload = {
                "character_name": encoded_character_name,
                "text": text,
                "split_sentence": False,
            }
            with self._http_client().post(
                self.tts_server_url + "tts", json=payload, stream=True, timeout=120
            ) as response:
                response.raise_for_status()
                chunks = [
                    chunk for chunk in response.iter_content(chunk_size=4096) if chunk
                ]

            if not chunks:
                logger.warning("Genie TTS returned empty audio stream.")
                return None

            if chunks[0][:4] == b"RIFF":
                with open(abs_file_path, "wb") as handle:
                    for chunk in chunks:
                        handle.write(chunk)
            else:
                if not self._write_pcm_chunks_as_wav(
                    chunks, abs_file_path, sample_rate=32000
                ):
                    raw_bytes = b"".join(chunks)
                    if not self._write_raw_stream_as_wav(
                        raw_bytes, abs_file_path, sample_rate=32000
                    ):
                        logger.warning(
                            "Genie TTS output is not valid WAV and conversion failed."
                        )
                        return None

            if not os.path.exists(abs_file_path):
                logger.warning("Genie TTS did not create output file: %s", abs_file_path)
                return None

            return abs_file_path
        except Exception as exc:
            logger.error("Genie TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        """Switch active Genie TTS character or convert ckpt/pth weights to ONNX."""
        if model_info is None:
            logger.warning("Genie TTS switch_model got empty model_info.")
            return
        new_character_name = model_info.get("character_name") or model_info.get("name")
        ckpt_model_path = model_info.get("gpt_model_path")
        pth_model_path = model_info.get("sovits_model_path")
        new_onnx_model_dir = model_info.get("onnx_model_dir")
        encoded_character_name = (
            self._encode_name(new_character_name) if new_character_name else ""
        )

        if not new_onnx_model_dir and encoded_character_name:
            new_onnx_model_dir = str((Path("onnx") / encoded_character_name).resolve())

        if new_onnx_model_dir and not self._has_onnx_files(new_onnx_model_dir):
            if ckpt_model_path and pth_model_path:
                try:
                    self._convert_model_to_onnx(
                        character_name=new_character_name or "unknown",
                        ckpt_model_path=ckpt_model_path,
                        pth_model_path=pth_model_path,
                        onnx_dir=new_onnx_model_dir,
                    )
                except Exception as exc:
                    logger.error("Auto convert ONNX failed: %s", exc)
            else:
                logger.warning("ONNX dir missing and no ckpt/pth path provided.")

        if new_onnx_model_dir and self.onnx_model_dir != new_onnx_model_dir:
            self.onnx_model_dir = new_onnx_model_dir
            self.loaded_character_name = None

        if new_character_name and self.character_name != new_character_name:
            self.character_name = new_character_name
            self.loaded_character_name = None

        if (
            self.character_name
            and self.onnx_model_dir
            and self.loaded_character_name != self.character_name
        ):
            logger.info("Switching Genie TTS character to: %s", self.character_name)
            self._load_character_model()

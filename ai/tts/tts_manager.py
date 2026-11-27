"""TTS playback queue manager and compatibility factory wrapper."""

from __future__ import annotations

from pathlib import Path
import queue
import threading
import time
from typing import Any
import uuid

import requests

from ai.tts.registry import create_tts_adapter, get_tts_adapter_registry
from ai.tts.server_process import start_server_process
from ai.tts.tts_adapter import (  # noqa: F401
    CosyVoiceAdapter,
    GPTSoVitsAdapter,
    GenieTTSAdapter,
    IndexTTSAdapter,
    KaggleGPTSoVitsAdapter,
    Qwen3TTSLlamaAdapter,
    TTSAdapter,
)
from ai.tts.voice_tags import strip_inline_voice_tags
from sdk.voice_lang import resolve_character_voice_language


class TTSAdapterFactory:
    """Compatibility wrapper backed by the process-wide TTS ``AdapterRegistry``."""

    _adapters = get_tts_adapter_registry().as_mutable_mapping()

    @staticmethod
    def create_adapter(
        adapter_name: str,
        *,
        wait_until_ready: bool = False,
        **kwargs: Any,
    ) -> TTSAdapter:
        """Create and return a ``TTSAdapter`` instance for ``adapter_name``."""
        return create_tts_adapter(
            adapter_name,
            wait_until_ready=wait_until_ready,
            **kwargs,
        )


class TTSManager:
    """Manage TTS synthesis cache, retries, and sequential character audio delivery."""

    def __init__(
        self,
        character_ui_url: str = "http://localhost:7888/alive",
        tts_server_url: str = "http://127.0.0.1:9880/",
        *,
        audio_cache_dir: str | Path | None = None,
        unique_cache_files: bool = False,
    ) -> None:
        self.audio_cache_dir = (
            Path(audio_cache_dir) if audio_cache_dir else Path("cache") / "audio"
        )
        self.unique_cache_files = unique_cache_files
        self.character_ui_url = character_ui_url
        self.cache_num = 100
        self.index = 0

        self.audio_cache_dir.mkdir(exist_ok=True, parents=True)
        self.tts_adapter: Any = None

        self.task_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

        self.voice_language = "ja"

    def set_tts_adapter(self, adapter: TTSAdapter) -> None:
        """Allow switching the TTS adapter at runtime."""
        self.tts_adapter = adapter

    @staticmethod
    def _is_valid_audio_file(path: str | Path | None) -> bool:
        if not path:
            return False
        try:
            p = Path(path)
            return p.is_file() and p.stat().st_size > 0
        except OSError:
            return False

    def generate_tts(
        self,
        text: str,
        text_processor: Any = None,
        ref_audio_path: str | None = None,
        prompt_text: str | None = None,
        prompt_lang: str | None = None,
        character_name: str | None = None,
        speed_factor: float | None = None,
        voice_instruct: str | None = None,
    ) -> str:
        """Generate TTS audio using the currently active adapter."""
        print("Generating speech")

        if text_processor:
            text = text_processor.remove_parentheses(text)
            text = text_processor.html_to_plain_qt(text)
            lang_probe = strip_inline_voice_tags(text) or text
            language = text_processor.decide_language(lang_probe)
            text = text_processor.replace_names(text)
            effective_voice_lang = resolve_character_voice_language(
                self.voice_language,
                prompt_lang=prompt_lang,
                prompt_text=prompt_text,
                speech_text=strip_inline_voice_tags(text) or text,
                fallback=language or "ja",
            )
            if language != effective_voice_lang:
                text = text_processor.libre_translate(
                    text, source=language, target=effective_voice_lang
                )
            if effective_voice_lang == "ja" and character_name in {
                "狛枝凪斗",
                "仆役",
                "小狛枝",
            }:
                text = text_processor.replace_watashi(text)
        else:
            effective_voice_lang = resolve_character_voice_language(
                self.voice_language,
                prompt_lang=prompt_lang,
                prompt_text=prompt_text,
                speech_text=strip_inline_voice_tags(text) or text,
            )

        if not ref_audio_path and getattr(self.tts_adapter, "requires_ref_audio", True):
            print("No reference audio provided")
            return ""

        extra_kwargs: dict[str, Any] = {}
        clean_instruct = str(voice_instruct or "").strip()
        if clean_instruct and bool(
            getattr(self.tts_adapter, "supports_voice_instruction", False)
        ):
            extra_kwargs["voice_instruct"] = clean_instruct

        filename = (
            uuid.uuid4().hex
            if self.unique_cache_files
            else str(self.index % self.cache_num)
        )
        final_path = self.audio_cache_dir / f"{filename}.wav"
        self.index += 1
        tmp_path = final_path.with_suffix(final_path.suffix + ".part")

        attempts = 2
        for attempt in range(1, attempts + 1):
            tmp_path.unlink(missing_ok=True)
            result = self.tts_adapter.generate_speech(
                text=text,
                file_path=str(tmp_path),
                ref_audio_path=ref_audio_path,
                prompt_text=prompt_text,
                prompt_lang=prompt_lang,
                text_lang=effective_voice_lang,
                character_name=character_name,
                speed_factor=speed_factor,
                **extra_kwargs,
            )
            if result and self._is_valid_audio_file(tmp_path):
                tmp_path.replace(final_path)
                return str(final_path)
            print(
                f"TTS generation returned no usable audio (attempt {attempt}/{attempts})."
            )
            tmp_path.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(0.35 * attempt)
        return ""

    def set_language(self, language: str) -> None:
        """Set the target voice language."""
        self.voice_language = language

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        """Switch the TTS model via the active adapter."""
        if model_info is None:
            print("No model info provided, cannot switch model.")
            return
        self.tts_adapter.switch_model(model_info)

    def _process_queue(self) -> None:
        """Worker thread to process queued speak/sing requests sequentially."""
        while True:
            task = self.task_queue.get()
            if task is None:
                break
            try:
                if task["type"] == "speak":
                    self._send_audio_to_character(task["file_path"])
                elif task["type"] == "sing":
                    self._send_song_to_character(
                        task["voice_path"], task["music_path"]
                    )
            except Exception as exc:
                print(f"TTS task failed: {exc}")
            finally:
                self.task_queue.task_done()

    def queue_speech(self, text: str, language_processor: Any = None) -> None:
        """Synthesize and enqueue speech audio for playback."""
        file_path = self.generate_tts(text, language_processor)
        if file_path:
            self.task_queue.put({"type": "speak", "file_path": file_path})

    def queue_song(self, voice_path: str, music_path: str) -> None:
        """Enqueue a song playback request."""
        self.task_queue.put(
            {"type": "sing", "voice_path": voice_path, "music_path": music_path}
        )

    def _send_audio_to_character(self, file_path: str) -> None:
        params = {"type": "speak", "speech_path": file_path}
        try:
            response = requests.post(self.character_ui_url, json=params)
            if response.status_code == 200:
                print(f"Audio sent successfully: {file_path}")
            else:
                print(f"Failed to send audio: {response.text}")
        except Exception as exc:
            print(f"Failed to send audio to character UI: {exc}")

    def _send_song_to_character(self, voice_path: str, music_path: str) -> None:
        params = {"type": "sing", "voice_path": voice_path, "music_path": music_path}
        try:
            response = requests.post(self.character_ui_url, json=params)
            if response.status_code == 200:
                print(f"Song sent successfully: {voice_path}, {music_path}")
            else:
                print(f"Failed to send song: {response.text}")
        except Exception as exc:
            print(f"Failed to send song to character UI: {exc}")

    def load_tts_model(self, gpt_sovits_work_path: str = "") -> None:
        """Launch a GPT-SoVITS server process from the configured directory."""
        work_dir = str(gpt_sovits_work_path or "").strip()
        if not work_dir:
            raise ValueError("gpt_sovits_work_path is required to launch GPT-SoVITS")
        base = Path(work_dir)
        embedded_python = base / "runtime" / "python.exe"
        script_path = base / "api_v2.py"
        start_server_process(str(embedded_python), str(script_path), cwd=base)

    def shutdown(self, *, stop_server: bool = True) -> None:
        """Shut down the queue, worker thread, and TTS server process."""
        self.task_queue.put(None)
        self.worker_thread.join()
        if stop_server and hasattr(self.tts_adapter, "stop_server"):
            self.tts_adapter.stop_server()

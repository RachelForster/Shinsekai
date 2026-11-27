"""Fish Audio S2 Pro TTS adapter supporting official cloud API and local fish-speech servers."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

from ai.tts.adapters.fish_audio_protocol import (
    DEFAULT_FISH_AUDIO_DECODER_CONFIG,
    DEFAULT_FISH_AUDIO_MODEL,
    DEFAULT_FISH_AUDIO_URL,
    FISH_AUDIO_CLOUD_HOSTS,
    build_fish_audio_config_schema,
    build_fish_speech_server_cmd,
    find_fish_speech_server_script,
    normalize_prosody_speed,
    pack_msgpack,
    parse_character_reference_ids,
    resolve_fish_audio_endpoints,
    resolve_local_fish_speech_launch,
)
from ai.tts.adapters.local_http import LocalHttpTTSAdapter, format_http_error, is_local_server_url
from core.adapters import builtin_adapter
from core.storage.layout import StorageLayout
from sdk.logging import get_logger

logger = get_logger(__name__)


@builtin_adapter("fish-audio-s2-pro", label="Fish Audio S2 Pro", order=70)
class FishAudioS2ProAdapter(LocalHttpTTSAdapter):
    """Text-to-speech adapter for Fish Audio S2 Pro cloud and self-hosted HTTP endpoints."""

    SERVICE_NAME = "Fish Audio S2 Pro"
    STARTUP_TIMEOUT_SECONDS = 300.0
    STARTUP_POLL_INTERVAL_SECONDS = 0.5
    requires_ref_audio = False

    def __init__(
        self,
        base_url: str = DEFAULT_FISH_AUDIO_URL,
        fish_speech_dir: str = "",
        *,
        api_key: str = "",
        model: str = DEFAULT_FISH_AUDIO_MODEL,
        reference_id: str = "",
        character_reference_ids: str | Mapping[str, Any] = "",
        latency: str = "normal",
        chunk_length: int = 200,
        temperature: float = 0.7,
        top_p: float = 0.7,
        repetition_penalty: float | None = None,
        normalize: bool = True,
        enable_inline_tags: bool = True,
        request_timeout: float = 120.0,
        llama_checkpoint_path: str = "",
        decoder_checkpoint_path: str = "",
        decoder_config_name: str = DEFAULT_FISH_AUDIO_DECODER_CONFIG,
        python_path: str = "",
        compile_model: bool = False,
        half_precision: bool = False,
        extra_args: str = "",
        project_root: str | os.PathLike[str] | None = None,
        **_ignored: Any,
    ) -> None:
        effective_url = str(base_url or DEFAULT_FISH_AUDIO_URL).strip() or DEFAULT_FISH_AUDIO_URL
        base_root, self._tts_endpoint, self._health_endpoint = resolve_fish_audio_endpoints(
            effective_url
        )
        self.tts_server_url = self._init_http_runtime(base_root)

        self.api_key = str(api_key or os.environ.get("FISH_API_KEY", "")).strip()
        self.model = str(model or DEFAULT_FISH_AUDIO_MODEL).strip() or DEFAULT_FISH_AUDIO_MODEL
        self.reference_id = str(reference_id or "").strip()
        self.character_reference_ids = parse_character_reference_ids(character_reference_ids)
        self._override_reference_id = ""

        clean_latency = str(latency or "normal").strip().lower()
        self.latency = "balanced" if clean_latency == "balanced" else "normal"
        self.chunk_length = max(100, min(300, int(chunk_length)))
        self.temperature = max(0.1, min(1.0, float(temperature)))
        self.top_p = max(0.1, min(1.0, float(top_p)))
        self.repetition_penalty = (
            None
            if repetition_penalty is None or repetition_penalty == ""
            else max(0.9, min(2.0, float(repetition_penalty)))
        )
        self.normalize = bool(normalize)
        self.enable_inline_tags = bool(enable_inline_tags)
        self.request_timeout = max(5.0, float(request_timeout))

        self.work_path = str(fish_speech_dir or "").strip() or None
        self.fish_speech_dir = self.work_path or ""
        self.llama_checkpoint_path = str(llama_checkpoint_path or "").strip()
        self.decoder_checkpoint_path = str(decoder_checkpoint_path or "").strip()
        self.decoder_config_name = (
            str(decoder_config_name or DEFAULT_FISH_AUDIO_DECODER_CONFIG).strip()
            or DEFAULT_FISH_AUDIO_DECODER_CONFIG
        )
        self.python_path = str(python_path or "").strip()
        self.compile_model = bool(compile_model)
        self.half_precision = bool(half_precision)
        self.extra_args = str(extra_args or "").strip()
        self.project_root = project_root

        self._logs: deque[str] = deque(maxlen=40)
        self._ref_audio_cache: dict[tuple[str, int, int], bytes] = {}
        self._start_server_process()

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        """Return configurable Fish Audio S2 Pro adapter fields for API settings."""
        return build_fish_audio_config_schema()
    @property
    def supports_inline_voice_tags(self) -> bool:
        """Whether Fish Audio S2 Pro advertises inline ``[...]`` tag guidance."""
        return self.enable_inline_tags

    @property
    def owns_server_process(self) -> bool:
        """Whether this adapter spawned the local fish-speech server process."""
        return self._server_process is not None

    def _is_local_server_url(self) -> bool:
        return is_local_server_url(self.tts_server_url)

    def _is_official_cloud_url(self) -> bool:
        host = (urlparse(self.tts_server_url).hostname or "").lower()
        return host in FISH_AUDIO_CLOUD_HOSTS

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _server_is_reachable(self) -> bool:
        try:
            response = self._session.get(
                self._health_endpoint,
                headers=self._auth_headers(),
                timeout=2.0,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _drain_logs(self, proc: subprocess.Popen[str]) -> None:
        stream = proc.stdout
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.rstrip("\r\n")
                if line:
                    self._logs.append(line)
        except Exception:
            pass

    def _start_server_process(self) -> None:
        if not self._is_local_server_url():
            return
        if self._server_is_reachable():
            return
        if not self.work_path:
            default_dir = StorageLayout.from_env(self.project_root).model_dir(
                "fish-audio-s2-pro"
            )
            if find_fish_speech_server_script(default_dir) is None:
                raise RuntimeError(
                    f"Local Fish Audio S2 Pro server is not reachable at {self.tts_server_url}; "
                    "start tools/api_server.py manually or configure the fish-speech directory."
                )

        python_exe, api_script, llama_ckpt, decoder_ckpt, work_dir = (
            resolve_local_fish_speech_launch(
                work_path=self.work_path,
                llama_checkpoint_path=self.llama_checkpoint_path,
                decoder_checkpoint_path=self.decoder_checkpoint_path,
                python_path=self.python_path,
                project_root=self.project_root,
            )
        )

        cmd = build_fish_speech_server_cmd(
            python_exe=python_exe,
            api_script=api_script,
            server_url=self.tts_server_url,
            llama_ckpt=llama_ckpt,
            decoder_ckpt=decoder_ckpt,
            decoder_config_name=self.decoder_config_name,
            compile_model=self.compile_model,
            half_precision=self.half_precision,
            api_key=self.api_key,
            extra_args=self.extra_args,
        )

        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "cwd": str(work_dir),
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(cmd, **popen_kwargs)
        self._server_process = proc
        threading.Thread(
            target=self._drain_logs,
            args=(proc,),
            name="fish-audio-s2-pro-logs",
            daemon=True,
        ).start()

    def wait_until_ready(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float | None = None,
    ) -> None:
        """Validate cloud credentials or poll the local fish-speech health endpoint."""
        if not self._is_local_server_url():
            if self._is_official_cloud_url() and not self.api_key:
                raise ValueError(
                    "Fish Audio API key is required when using https://api.fish.audio."
                )
            return None

        timeout = max(
            0.0,
            float(
                self.STARTUP_TIMEOUT_SECONDS
                if timeout_seconds is None
                else timeout_seconds
            ),
        )
        interval = max(
            0.01,
            float(
                self.STARTUP_POLL_INTERVAL_SECONDS
                if poll_interval_seconds is None
                else poll_interval_seconds
            ),
        )
        deadline = time.monotonic() + timeout
        while True:
            if self._server_is_reachable():
                return None
            proc = self._server_process
            if proc is not None:
                rc = proc.poll()
                if rc is not None:
                    tail = " | ".join(list(self._logs)[-5:])
                    detail = f": {tail}" if tail else ""
                    raise RuntimeError(
                        f"Fish Audio S2 Pro server exited before becoming ready (code {rc}){detail}"
                    )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Fish Audio S2 Pro server did not become ready within {timeout:g} seconds."
                )
            time.sleep(min(interval, remaining))

    def _read_ref_audio(self, path: Path) -> bytes:
        resolved = path.expanduser().resolve()
        stat = resolved.stat()
        key = (resolved.as_posix(), int(stat.st_mtime_ns), int(stat.st_size))
        cached = self._ref_audio_cache.get(key)
        if cached is not None:
            return cached
        data = resolved.read_bytes()
        if len(self._ref_audio_cache) >= 16:
            oldest_key = next(iter(self._ref_audio_cache))
            self._ref_audio_cache.pop(oldest_key, None)
        self._ref_audio_cache[key] = data
        return data

    def _resolve_reference_id(self, kwargs: Mapping[str, Any]) -> str:
        explicit = str(kwargs.get("reference_id") or kwargs.get("voice") or "").strip()
        if explicit:
            return explicit
        if self._override_reference_id:
            return self._override_reference_id
        char_name = str(kwargs.get("character_name") or "").strip()
        if char_name and char_name in self.character_reference_ids:
            return self.character_reference_ids[char_name]
        return self.reference_id

    def generate_speech(
        self,
        text: str,
        file_path: str | None = None,
        **kwargs: Any,
    ) -> str | None:
        """Synthesize speech audio via ``POST /v1/tts`` as WAV."""
        clean_text = str(text or "").strip()
        if not clean_text:
            return None
        voice_instruct = str(kwargs.get("voice_instruct") or "").strip().strip("[]").strip()
        if voice_instruct and not clean_text.startswith("["):
            clean_text = f"[{voice_instruct}] {clean_text}"
        if self._is_official_cloud_url() and not self.api_key:
            logger.warning("Fish Audio API key is empty.")
            return None

        active_ref_id = self._resolve_reference_id(kwargs)
        references: list[dict[str, Any]] | None = None
        if not active_ref_id:
            ref_audio_path = str(kwargs.get("ref_audio_path") or "").strip()
            if ref_audio_path:
                ref_file = Path(ref_audio_path).expanduser()
                if not ref_file.is_file():
                    logger.error("Fish Audio reference audio not found: %s", ref_audio_path)
                    return None
                ref_bytes = self._read_ref_audio(ref_file)
                prompt_text = str(kwargs.get("prompt_text") or "").strip()
                references = [{"audio": ref_bytes, "text": prompt_text}]

        payload: dict[str, Any] = {
            "text": clean_text,
            "format": "wav",
            "chunk_length": self.chunk_length,
            "normalize": self.normalize,
            "latency": self.latency,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if self.repetition_penalty is not None:
            payload["repetition_penalty"] = self.repetition_penalty

        speed = normalize_prosody_speed(kwargs.get("speed_factor"))
        if speed is not None:
            payload["prosody"] = {"speed": speed}

        if active_ref_id:
            payload["reference_id"] = active_ref_id
        elif references is not None:
            payload["references"] = references

        headers = self._auth_headers()
        if self.model:
            headers["model"] = self.model

        try:
            if "references" in payload:
                headers["Content-Type"] = "application/msgpack"
                response = self._session.post(
                    self._tts_endpoint,
                    data=pack_msgpack(payload),
                    headers=headers,
                    timeout=self.request_timeout,
                )
            else:
                headers["Content-Type"] = "application/json"
                response = self._session.post(
                    self._tts_endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.request_timeout,
                )
            if not response.ok:
                raise RuntimeError(format_http_error(response, "Fish Audio S2 Pro TTS"))
            content = response.content
            if len(content) <= 44 or not content.startswith(b"RIFF"):
                raise RuntimeError("Fish Audio S2 Pro returned invalid or empty WAV payload.")

            out_path = Path(file_path or "temp_fish_audio_s2_pro.wav")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(content)
            return os.path.abspath(out_path)
        except Exception as exc:
            logger.error("Fish Audio S2 Pro TTS generation failed: %s", exc)
            return None

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        """Switch active Fish Audio model and per-character reference voice override."""
        if not isinstance(model_info, dict):
            return
        if "model" in model_info:
            next_model = str(model_info.get("model") or "").strip()
            if next_model:
                self.model = next_model
        if "reference_id" in model_info:
            self._override_reference_id = str(model_info.get("reference_id") or "").strip()
        elif "voice" in model_info:
            self._override_reference_id = str(model_info.get("voice") or "").strip()
        elif "character_name" in model_info:
            char_name = str(model_info.get("character_name") or "").strip()
            self._override_reference_id = self.character_reference_ids.get(char_name, "")

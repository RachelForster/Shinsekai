"""Text-to-speech adapter for Qwen3-TTS GGUF models served by llama.cpp."""

from __future__ import annotations

import base64
from collections import deque
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests

from core.storage.layout import StorageLayout
from sdk.adapters import TTSAdapter

DEFAULT_QWEN3_TTS_URL = "http://127.0.0.1:9882/"
_LOCAL_HOSTS = frozenset({"", "127.0.0.1", "localhost", "0.0.0.0", "::1"})
_QUANT_PREFERENCE = ("q8_0", "q4_k_m", "bf16", "f16")

_LANGUAGE_ALIASES = {
    "": "",
    "auto": "",
    "all_ja": "japanese",
    "all_ko": "korean",
    "all_yue": "cantonese",
    "all_zh": "chinese",
    "cantonese": "cantonese",
    "chinese": "chinese",
    "cn": "chinese",
    "de": "german",
    "de_de": "german",
    "en": "english",
    "en_gb": "english",
    "en_us": "english",
    "english": "english",
    "es": "spanish",
    "fr": "french",
    "french": "french",
    "german": "german",
    "it": "italian",
    "italian": "italian",
    "ja": "japanese",
    "ja_jp": "japanese",
    "japanese": "japanese",
    "jp": "japanese",
    "ko": "korean",
    "ko_kr": "korean",
    "korean": "korean",
    "portuguese": "portuguese",
    "pt": "portuguese",
    "pt_br": "portuguese",
    "ru": "russian",
    "russian": "russian",
    "spanish": "spanish",
    "yue": "cantonese",
    "zh": "chinese",
    "zh_cn": "chinese",
    "zh_hk": "cantonese",
    "zh_tw": "chinese",
}


def _is_local_server_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def _normalize_qwen3_tts_lang(raw: str | None) -> str:
    clean = str(raw or "").strip().lower().replace("-", "_")
    if clean in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[clean]
    base = clean.split("_", 1)[0]
    return _LANGUAGE_ALIASES.get(base, clean)


def _rank_gguf(path: Path) -> tuple[int, str]:
    lowered = path.name.lower()
    for idx, token in enumerate(_QUANT_PREFERENCE):
        if token in lowered:
            return (idx, lowered)
    return (len(_QUANT_PREFERENCE), lowered)


def _pick_gguf(dirs: list[Path], *, is_mmproj: bool) -> str:
    candidates: list[Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for entry in directory.glob("*.gguf"):
            if not entry.is_file():
                continue
            has_mmproj = "mmproj" in entry.name.lower()
            if has_mmproj == is_mmproj:
                candidates.append(entry)
    if not candidates:
        return ""
    best = min(candidates, key=_rank_gguf)
    return best.resolve().as_posix()


def _resolve_server_executable(explicit: str, candidate_dirs: list[Path]) -> str:
    exe_name = "llama-server.exe" if os.name == "nt" else "llama-server"
    raw = str(explicit or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_file():
            return path.resolve().as_posix()
        for sub in (path / "llama.cpp" / exe_name, path / exe_name):
            if sub.is_file():
                return sub.resolve().as_posix()
        return raw

    for directory in candidate_dirs:
        for sub in (directory / "llama.cpp" / exe_name, directory / exe_name):
            if sub.is_file():
                return sub.resolve().as_posix()

    which_hit = shutil.which(exe_name) or shutil.which("llama-server")
    return Path(which_hit).resolve().as_posix() if which_hit else ""


def discover_qwen3_tts_files(
    *,
    work_path: str | Path | None = None,
    model_path: str = "",
    mmproj_path: str = "",
    llama_server_path: str = "",
    project_root: str | os.PathLike[str] | None = None,
) -> tuple[str, str, str]:
    """Resolve ``(llama_server, model_gguf, mmproj_gguf)`` from explicit args or StorageLayout."""
    layout = StorageLayout.from_env(project_root)
    weight_dirs: list[Path] = []
    work_str = str(work_path or "").strip()
    if work_str:
        w = Path(work_str).expanduser()
        weight_dirs.append(w.parent if w.is_file() else w)
    weight_dirs.extend(
        [
            layout.model_dir("qwen3-tts-gguf"),
            layout.cache_dir / "qwen3-tts-gguf",
        ]
    )

    resolved_model = str(model_path or "").strip()
    if resolved_model:
        resolved_model = Path(resolved_model).expanduser().resolve().as_posix()
    else:
        resolved_model = _pick_gguf(weight_dirs, is_mmproj=False)

    resolved_mmproj = str(mmproj_path or "").strip()
    if resolved_mmproj:
        resolved_mmproj = Path(resolved_mmproj).expanduser().resolve().as_posix()
    else:
        mmproj_dirs = list(weight_dirs)
        if resolved_model:
            mmproj_dirs.insert(0, Path(resolved_model).parent)
        resolved_mmproj = _pick_gguf(mmproj_dirs, is_mmproj=True)

    binary_dirs = [
        *weight_dirs,
        layout.model_dir("perception-gguf"),
        layout.cache_dir / "perception-gguf",
    ]
    resolved_server = _resolve_server_executable(llama_server_path, binary_dirs)
    return resolved_server, resolved_model, resolved_mmproj


class Qwen3TTSLlamaAdapter(TTSAdapter):
    """Adapter for Qwen3-TTS GGUF models hosted via llama.cpp ``llama-server``."""

    STARTUP_TIMEOUT_SECONDS = 300.0
    STARTUP_POLL_INTERVAL_SECONDS = 0.5

    def __init__(
        self,
        tts_server_url: str = DEFAULT_QWEN3_TTS_URL,
        gpt_sovits_work_path: str | None = None,
        tts_work_path: str | None = None,
        model_path: str = "",
        mmproj_path: str = "",
        llama_server_path: str = "",
        voice: str = "",
        default_lang: str = "",
        n_gpu_layers: int = 99,
        ctx_size: int = 4096,
        threads: int = 0,
        request_timeout: float = 180.0,
        extra_args: str = "",
        project_root: str | os.PathLike[str] | None = None,
    ) -> None:
        raw_url = str(tts_server_url or DEFAULT_QWEN3_TTS_URL).strip() or DEFAULT_QWEN3_TTS_URL
        self.tts_server_url = raw_url.rstrip("/") + "/"
        self.work_path = str(tts_work_path or gpt_sovits_work_path or "").strip() or None
        self.model_path = str(model_path or "").strip()
        self.mmproj_path = str(mmproj_path or "").strip()
        self.llama_server_path = str(llama_server_path or "").strip()
        self.voice = str(voice or "").strip()
        self.default_lang = str(default_lang or "").strip()
        self.n_gpu_layers = int(n_gpu_layers)
        self.ctx_size = max(512, int(ctx_size))
        self.threads = max(0, int(threads))
        self.request_timeout = max(5.0, float(request_timeout))
        self.extra_args = str(extra_args or "").strip()
        self.project_root = project_root

        self._override_voice = ""
        self._server_process: subprocess.Popen[str] | None = None
        self._logs: deque[str] = deque(maxlen=60)
        self._ref_cache_key: tuple[str, int, int] | None = None
        self._ref_cache_b64 = ""
        self._session = requests.Session()
        if self._is_local_server_url():
            self._session.trust_env = False

        self._start_server_process()

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "model_path": {
                "type": "str",
                "label": "Backbone GGUF model path (optional)",
                "default": "",
            },
            "mmproj_path": {
                "type": "str",
                "label": "Multimodal mmproj GGUF path (optional)",
                "default": "",
            },
            "llama_server_path": {
                "type": "str",
                "label": "llama-server executable path (optional)",
                "default": "",
            },
            "voice": {
                "type": "str",
                "label": "Preset speaker voice (leave blank for reference audio cloning)",
                "default": "",
            },
            "default_lang": {
                "type": "str",
                "label": "Default TTS language override (optional)",
                "default": "",
            },
            "n_gpu_layers": {
                "type": "int",
                "label": "GPU offload layers (-ngl)",
                "default": 99,
                "min": 0,
                "max": 200,
            },
            "ctx_size": {
                "type": "int",
                "label": "Context window size (--ctx-size)",
                "default": 4096,
                "min": 512,
                "max": 32768,
            },
            "threads": {
                "type": "int",
                "label": "CPU threads (0 = auto)",
                "default": 0,
                "min": 0,
                "max": 128,
            },
            "request_timeout": {
                "type": "float",
                "label": "Synthesis HTTP timeout (seconds)",
                "default": 180.0,
                "min": 5.0,
                "max": 1200.0,
                "step": 5.0,
            },
            "extra_args": {
                "type": "str",
                "label": "Extra llama-server CLI arguments",
                "default": "",
            },
        }

    @property
    def requires_ref_audio(self) -> bool:
        return not bool(self._override_voice or self.voice)

    def _is_local_server_url(self) -> bool:
        return _is_local_server_url(self.tts_server_url)

    def _server_is_reachable(self) -> bool:
        try:
            response = self._session.get(self.tts_server_url + "health", timeout=2.0)
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
        if self._server_is_reachable():
            return
        if not self._is_local_server_url():
            return

        llama_server, model, mmproj = discover_qwen3_tts_files(
            work_path=self.work_path,
            model_path=self.model_path,
            mmproj_path=self.mmproj_path,
            llama_server_path=self.llama_server_path,
            project_root=self.project_root,
        )
        default_dir = StorageLayout.from_env(self.project_root).model_dir("qwen3-tts-gguf")
        if not llama_server or not Path(llama_server).is_file():
            raise FileNotFoundError(
                f"llama-server executable not found (checked {default_dir / 'llama.cpp'} and perception-gguf)."
            )
        if not model or not Path(model).is_file():
            raise FileNotFoundError(
                f"Qwen3-TTS GGUF backbone not found (expected under {default_dir})."
            )
        if not mmproj or not Path(mmproj).is_file():
            raise FileNotFoundError(
                f"Qwen3-TTS mmproj GGUF not found (expected under {default_dir})."
            )

        parsed = urlparse(self.tts_server_url)
        host = (parsed.hostname or "").strip().lower()
        bind_host = "0.0.0.0" if host == "0.0.0.0" else "127.0.0.1"
        port = int(parsed.port or 9882)

        cmd = [
            llama_server,
            "-m",
            model,
            "--mmproj",
            mmproj,
            "--host",
            bind_host,
            "--port",
            str(port),
            "-ngl",
            str(self.n_gpu_layers),
            "--ctx-size",
            str(self.ctx_size),
            "--parallel",
            "1",
            "--no-webui",
        ]
        if self.threads > 0:
            cmd.extend(["-t", str(self.threads)])
        if self.extra_args:
            cmd.extend(shlex.split(self.extra_args, posix=(os.name != "nt")))

        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "cwd": str(Path(llama_server).parent),
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(cmd, **popen_kwargs)
        self._server_process = proc
        threading.Thread(
            target=self._drain_logs,
            args=(proc,),
            name="qwen3-tts-llama-logs",
            daemon=True,
        ).start()

    def wait_until_ready(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float | None = None,
    ) -> None:
        timeout = max(0.0, float(self.STARTUP_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds))
        interval = max(0.01, float(self.STARTUP_POLL_INTERVAL_SECONDS if poll_interval_seconds is None else poll_interval_seconds))
        deadline = time.monotonic() + timeout
        while True:
            if self._server_is_reachable():
                return
            proc = self._server_process
            if proc is not None:
                rc = proc.poll()
                if rc is not None:
                    tail = " | ".join(list(self._logs)[-5:])
                    detail = f": {tail}" if tail else ""
                    raise RuntimeError(f"Qwen3-TTS llama-server exited before becoming ready (code {rc}){detail}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Qwen3-TTS llama-server did not become ready within {timeout:g} seconds.")
            time.sleep(min(interval, remaining))

    def stop_server(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
        proc = self._server_process
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
            self._server_process = None

    def _encode_ref_audio(self, ref_audio_path: str) -> str:
        path = Path(ref_audio_path).expanduser().resolve()
        stat = path.stat()
        key = (path.as_posix(), int(stat.st_mtime_ns), int(stat.st_size))
        if self._ref_cache_key != key:
            self._ref_cache_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            self._ref_cache_key = key
        return self._ref_cache_b64

    def generate_speech(self, text, file_path=None, **kwargs):
        clean_text = str(text or "").strip()
        if not clean_text:
            return None

        active_voice = str(kwargs.get("voice") or self._override_voice or self.voice or "").strip()
        ref_audio_path = str(kwargs.get("ref_audio_path") or "").strip()
        speaker_ref_b64 = ""
        if not active_voice and ref_audio_path:
            ref_file = Path(ref_audio_path).expanduser()
            if not ref_file.is_file():
                print(f"Qwen3-TTS reference audio not found: {ref_audio_path}")
                return None
            speaker_ref_b64 = self._encode_ref_audio(str(ref_file))

        lang = _normalize_qwen3_tts_lang(kwargs.get("text_lang") or self.default_lang)
        payload: dict[str, Any] = {
            "input": clean_text,
            "response_format": "wav",
        }
        if lang:
            payload["lang"] = lang
        if active_voice:
            payload["voice"] = active_voice
        elif speaker_ref_b64:
            payload["speaker_ref_b64"] = speaker_ref_b64

        try:
            response = self._session.post(
                self.tts_server_url + "v1/audio/speech",
                json=payload,
                timeout=self.request_timeout,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            content = response.content
            if len(content) <= 44 or not content.startswith(b"RIFF"):
                raise RuntimeError("llama-server returned invalid or empty WAV payload.")

            out_path = Path(file_path or "temp_qwen3_tts.wav")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(content)
            return os.path.abspath(out_path)
        except Exception as exc:
            print(f"Qwen3-TTS GGUF generation failed: {exc}")
            return None

    def switch_model(self, model_info):
        if isinstance(model_info, dict) and "voice" in model_info:
            self._override_voice = str(model_info.get("voice") or "").strip()
        return None

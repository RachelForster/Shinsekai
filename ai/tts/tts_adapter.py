# tts_adapter.py
from sdk.adapters import TTSAdapter
import os
import requests
import threading
import queue
import base64
import hashlib
import math
import wave
import array
from pathlib import Path
import subprocess
import sys
import time
from typing import Optional, Callable
from urllib.parse import urlparse

from sdk.file_transactions import (
    atomic_binary_writer,
    atomic_write_bytes,
    capture_directory_identity,
    file_snapshot_is_stable,
    inspect_portable_directory_tree,
    open_binary_read_without_links,
    require_directory_identity,
)
from sdk.process_launch import (
    capture_launch_directory,
    capture_launch_file,
    isolated_python_environment,
    popen_with_stable_paths,
    run_with_stable_paths,
)
from sdk.path_contract import (
    managed_project_directory,
    project_root,
    require_directory_without_links,
    require_regular_file_without_links,
    require_symlink_free_absolute_path,
    resolve_executable_file,
    resolve_project_output_path,
    resolve_runtime_asset_read_path,
    safe_path_component,
    safe_path_component_with_suffix,
    validate_exact_path_text,
)


def _tts_output_path(file_path: str | os.PathLike[str] | None, prefix: str) -> Path:
    """Resolve adapter output without consulting the process working directory."""

    root = project_root()
    raw = (
        f"data/cache/audio/{prefix}_{os.urandom(4).hex()}.wav"
        if file_path is None
        else os.fspath(file_path)
    )
    output = resolve_project_output_path(raw, root=root)
    output.parent.mkdir(parents=True, exist_ok=True)
    require_directory_without_links(
        output.parent,
        field="TTS output directory",
    )
    return output


def _tts_work_path(value: str | os.PathLike[str] | None) -> str | None:
    """Resolve local engine work paths without consulting process cwd."""

    raw = os.fspath(value) if value is not None else ""
    if not raw:
        return None
    return resolve_runtime_asset_read_path(
        raw,
        root=project_root(),
        resource_prefixes=(),
    ).as_posix()


def _bundled_python_path(work_root: Path) -> Path | None:
    """Locate a native bundled interpreter without assuming Windows layout."""

    try:
        root = require_directory_without_links(
            work_root,
            field="TTS work directory",
        )
    except (OSError, ValueError):
        return None
    if os.name == "nt":
        relatives = (
            Path("runtime/python.exe"),
            Path("runtime/python3.exe"),
            Path("runtime/bin/python.exe"),
            Path("runtime/bin/python3.exe"),
        )
    else:
        relatives = (
            Path("runtime/bin/python3"),
            Path("runtime/bin/python"),
            Path("runtime/python3"),
            Path("runtime/python"),
        )
    for relative in relatives:
        candidate = root / relative
        if os.path.lexists(candidate):
            return resolve_executable_file(
                candidate,
                field="TTS Python executable",
            )
    return None


def _local_python_path(work_root: Path, *, service_name: str) -> Path:
    bundled = _bundled_python_path(work_root)
    if bundled is not None:
        return bundled
    if getattr(sys, "frozen", False):
        raise FileNotFoundError(
            f"{service_name} bundled runtime Python not found under: {work_root}"
        )
    return resolve_executable_file(
        Path(sys.executable),
        field="host Python executable",
    )


def _popen_local_python_service(
    *,
    service_name: str,
    work_root: Path,
    python_path: Path,
    script_path: Path,
    popen_factory=None,
):
    work_snapshot = capture_launch_directory(
        work_root,
        field=f"{service_name} work directory",
    )
    python_snapshot = capture_launch_file(
        python_path,
        field=f"{service_name} Python executable",
        executable=True,
    )
    script_snapshot = capture_launch_file(
        script_path,
        field=f"{service_name} startup script",
    )
    return popen_with_stable_paths(
        [python_snapshot.path, script_snapshot.path],
        cwd=work_snapshot,
        executable=python_snapshot,
        required_files=(script_snapshot,),
        env=isolated_python_environment(),
        popen_factory=subprocess.Popen if popen_factory is None else popen_factory,
    )


def _tts_service_input_path(
    value: str | os.PathLike[str] | None,
    *,
    local_service: bool,
    field: str,
) -> str:
    """Preserve remote path semantics while rooting local service inputs."""

    raw = os.fspath(value) if value is not None else ""
    if not raw:
        return ""
    if local_service:
        return resolve_runtime_asset_read_path(
            raw,
            root=project_root(),
        ).as_posix()
    validate_exact_path_text(
        raw,
        field=field,
        allow_non_native_absolute=True,
    )
    return raw


def _is_local_server_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"", "127.0.0.1", "localhost", "0.0.0.0", "::1"}


def _wait_for_http_service_ready(
    probe: Callable[[], bool],
    *,
    service_name: str,
    process,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> None:
    timeout = max(0.0, float(timeout_seconds))
    interval = max(0.01, float(poll_interval_seconds))
    deadline = time.monotonic() + timeout
    while True:
        if probe():
            return

        poll = getattr(process, "poll", None)
        if callable(poll):
            return_code = poll()
            if return_code is not None:
                raise RuntimeError(f"{service_name} server exited before becoming ready (code {return_code}).")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{service_name} server did not become ready within {timeout:g} seconds.")
        time.sleep(min(interval, remaining))


class GPTSoVitsAdapter(TTSAdapter):
    """
    Adapter for the GPT-SoVITS TTS service.
    It adapts the GPT-SoVITS API to the standard TTSAdapter interface.
    """
    STARTUP_TIMEOUT_SECONDS = 600.0
    STARTUP_POLL_INTERVAL_SECONDS = 0.5

    def __init__(self, tts_server_url="http://127.0.0.1:9880/", gpt_sovits_work_path = None):
        self.tts_server_url = tts_server_url.rstrip("/") + "/"
        self._session = requests.Session()
        if self._is_local_server_url():
            # Loopback services must not be routed through HTTP(S)_PROXY.
            self._session.trust_env = False
        self.sovits_model_path = ''
        self.gpt_model_path = ''
        self.gpt_sovits_work_path = _tts_work_path(gpt_sovits_work_path)
        self._server_process = None

        # Consider the user's input mistake
        if self.gpt_sovits_work_path and self.gpt_sovits_work_path.endswith(".py"):
            self.gpt_sovits_work_path = Path(self.gpt_sovits_work_path).parent.as_posix()


        # Load the model and start the server process here
        self._start_server_process()

    def stop_server(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None

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
        return _is_local_server_url(self.tts_server_url)

    def wait_until_ready(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float | None = None,
    ) -> None:
        _wait_for_http_service_ready(
            self._server_is_reachable,
            service_name="GPT-SoVITS",
            process=self._server_process,
            timeout_seconds=self.STARTUP_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds,
            poll_interval_seconds=(
                self.STARTUP_POLL_INTERVAL_SECONDS
                if poll_interval_seconds is None
                else poll_interval_seconds
            ),
        )

    @staticmethod
    def _response_error_text(response, action: str) -> str:
        try:
            payload = response.json()
            detail = payload.get("Exception") or payload.get("message") or str(payload)
        except ValueError:
            detail = response.text.strip()
        detail = detail.replace("\n", " ").strip()
        return f"{action} failed with HTTP {response.status_code}: {detail[:1000]}"

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        if self._server_is_reachable():
            print("GPT-SoVITS server is already reachable.")
            return

        if not self._is_local_server_url():
            print("Remote GPT-SoVITS server is not reachable; skip local auto-start.")
            return

        if not self.gpt_sovits_work_path:
            raise RuntimeError("Local GPT-SoVITS server is not reachable; set the GPT-SoVITS startup path.")

        os_path = require_directory_without_links(
            self.gpt_sovits_work_path,
            field="GPT-SoVITS work directory",
        )
        raw_api_path = os_path / "api_v2.py"
        if not os.path.lexists(raw_api_path):
            raise FileNotFoundError(
                f"GPT-SoVITS api_v2.py not found: {raw_api_path}"
            )
        api_path = require_regular_file_without_links(
            raw_api_path,
            field="GPT-SoVITS startup script",
        )

        python_path = _local_python_path(os_path, service_name="GPT-SoVITS")

        self._server_process = _popen_local_python_service(
            service_name="GPT-SoVITS",
            work_root=os_path,
            python_path=python_path,
            script_path=api_path,
        )
        print("GPT-SoVITS server starting...")

    def generate_speech(self, text, file_path=None, **kwargs):
        """
        Generates TTS audio using the GPT-SoVITS API.
        The kwargs dictionary can include parameters like ref_audio_path, prompt_text, etc.
        """

        # Parameters for the GPT-SoVITS API call
        speed_factor = kwargs.get("speed_factor")
        if speed_factor is None:
            speed_factor = 1.0
        try:
            batch_size = max(1, int(kwargs.get("batch_size", 1)))
        except (TypeError, ValueError):
            batch_size = 1

        reference_audio = _tts_service_input_path(
            kwargs.get("ref_audio_path"),
            local_service=self._is_local_server_url(),
            field="reference audio path",
        )
        params = {
            "ref_audio_path": reference_audio,
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
            response = self._session.post(self.tts_server_url + "tts", json=params, timeout=300)
            if not response.ok:
                raise RuntimeError(self._response_error_text(response, "TTS request"))

            output = _tts_output_path(file_path, "gpt_sovits")
            atomic_write_bytes(output, response.content)

            return output.as_posix()
        except Exception as e:
            print(f"GPT-SoVITS TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        """
        Switches the GPT-SoVITS models.
        `model_info` is expected to be a dictionary with 'gpt_model_path' and 'sovits_model_path'.
        """

        local_service = self._is_local_server_url()
        gpt_model_path = _tts_service_input_path(
            model_info.get("gpt_model_path"),
            local_service=local_service,
            field="GPT model path",
        )
        sovits_model_path = _tts_service_input_path(
            model_info.get("sovits_model_path"),
            local_service=local_service,
            field="SoVITS model path",
        )

        if self.sovits_model_path == sovits_model_path and self.gpt_model_path == gpt_model_path:
            print("No model switch needed, current models are already set.", self.gpt_model_path, self.sovits_model_path)
            return

        try:
            if gpt_model_path and gpt_model_path.endswith(".ckpt"):
                response = self._session.get(
                    self.tts_server_url + "set_gpt_weights",
                    params={"weights_path": gpt_model_path},
                    timeout=180,
                )
                if not response.ok:
                    raise RuntimeError(self._response_error_text(response, "GPT weight switch"))
                self.gpt_model_path = gpt_model_path
                print(f"gpt model switched successfully: {gpt_model_path}")
        except Exception as e:
            print(f"Failed to switch gpt model: {e}")
            raise

        try:
            if sovits_model_path and sovits_model_path.endswith(".pth"):
                response = self._session.get(
                    self.tts_server_url + "set_sovits_weights",
                    params={"weights_path": sovits_model_path},
                    timeout=180,
                )
                if not response.ok:
                    raise RuntimeError(self._response_error_text(response, "SoVITS weight switch"))
                self.sovits_model_path = sovits_model_path
                print(f"sovits model switched successfully: {sovits_model_path}")
        except Exception as e:
            print(f"Failed to switch sovits model: {e}")
            raise


def _is_kaggle_path(path: str) -> bool:
    return str(path or "").startswith("/kaggle/")


def _optional_remote_path(value: object, *, field: str) -> str:
    raw = str(value or "")
    if raw and (
        raw != raw.strip()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw
        )
    ):
        raise ValueError(f"{field} must not contain non-portable characters")
    if raw:
        validate_exact_path_text(
            raw,
            field=field,
            allow_non_native_absolute=True,
        )
    return raw


class KaggleGPTSoVitsAdapter(GPTSoVitsAdapter):
    """GPT-SoVITS adapter for a Kaggle-hosted API.

    Kaggle cannot read local Shinsekai paths like ``data/models/...``. By
    default this adapter assumes the notebook has already loaded the selected
    character model and only sends synthesis requests. Optional ``/kaggle/...``
    paths can be configured when explicit weight switching is needed.
    """

    def __init__(
        self,
        tts_server_url="http://127.0.0.1:9880/",
        gpt_sovits_work_path=None,
        remote_gpt_model_path: str = "",
        remote_sovits_model_path: str = "",
        remote_ref_audio_path: str = "/kaggle/working/shinsekai_ref_clean.wav",
        switch_weights: bool = False,
        text_split_method: str = "cut5",
        batch_size: int = 4,
        speed_factor: float = 1.0,
        use_character_speed: bool = False,
        parallel_infer: bool = True,
        split_bucket: bool = True,
        batch_threshold: float = 0.75,
        super_sampling: bool = False,
    ):
        self.remote_gpt_model_path = _optional_remote_path(
            remote_gpt_model_path,
            field="remote_gpt_model_path",
        )
        self.remote_sovits_model_path = _optional_remote_path(
            remote_sovits_model_path,
            field="remote_sovits_model_path",
        )
        self.remote_ref_audio_path = _optional_remote_path(
            remote_ref_audio_path,
            field="remote_ref_audio_path",
        )
        self.switch_weights = bool(switch_weights)
        self.text_split_method = str(text_split_method or "cut5").strip() or "cut5"
        try:
            self.batch_size = max(1, int(batch_size))
        except (TypeError, ValueError):
            self.batch_size = 4
        try:
            self.speed_factor = float(speed_factor)
        except (TypeError, ValueError):
            self.speed_factor = 1.0
        self.use_character_speed = bool(use_character_speed)
        self.parallel_infer = bool(parallel_infer)
        self.split_bucket = bool(split_bucket)
        try:
            self.batch_threshold = float(batch_threshold)
        except (TypeError, ValueError):
            self.batch_threshold = 0.75
        self.super_sampling = bool(super_sampling)
        super().__init__(tts_server_url=tts_server_url, gpt_sovits_work_path=None)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "remote_ref_audio_path": {
                "label": "Kaggle 参考音频路径",
                "type": "str",
                "default": "/kaggle/working/shinsekai_ref_clean.wav",
            },
            "switch_weights": {
                "label": "每次角色切换时请求 Kaggle 切权重",
                "type": "bool",
                "default": False,
            },
            "remote_gpt_model_path": {
                "label": "Kaggle GPT 模型路径",
                "type": "str",
                "default": "",
            },
            "remote_sovits_model_path": {
                "label": "Kaggle SoVITS 模型路径",
                "type": "str",
                "default": "",
            },
            "text_split_method": {
                "label": "GPT-SoVITS 分句方式",
                "type": "str",
                "default": "cut5",
            },
            "batch_size": {
                "label": "推理 batch_size（长文本可提速，OOM 降到 1）",
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 16,
            },
            "speed_factor": {
                "label": "固定语速倍率（1.0 最快且最稳）",
                "type": "float",
                "default": 1.0,
                "min": 0.5,
                "max": 2.0,
                "step": 0.05,
            },
            "use_character_speed": {
                "label": "使用角色 speech_speed（可能降低推理速度）",
                "type": "bool",
                "default": False,
            },
            "parallel_infer": {
                "label": "开启 parallel_infer",
                "type": "bool",
                "default": True,
            },
            "split_bucket": {
                "label": "开启 split_bucket",
                "type": "bool",
                "default": True,
            },
            "batch_threshold": {
                "label": "batch_threshold",
                "type": "float",
                "default": 0.75,
                "min": 0.1,
                "max": 1.0,
                "step": 0.05,
            },
            "super_sampling": {
                "label": "开启 super_sampling（更慢）",
                "type": "bool",
                "default": False,
            },
        }

    def _start_server_process(self):
        if self._server_is_reachable():
            print("Kaggle GPT-SoVITS server is reachable.")
        else:
            print("Kaggle GPT-SoVITS server is not reachable; start the Kaggle notebook and tunnel first.")

    def _configured_or_kaggle_path(self, configured: str, fallback: str) -> str:
        configured = _optional_remote_path(
            configured,
            field="configured Kaggle path",
        )
        fallback = _optional_remote_path(
            fallback,
            field="fallback Kaggle path",
        )
        if configured:
            return configured
        if _is_kaggle_path(fallback):
            return fallback
        return ""

    def switch_model(self, model_info):
        if not self.switch_weights:
            print("Kaggle GPT-SoVITS: skip weight switch; using the model currently loaded in Kaggle.")
            return

        model_info = model_info or {}
        gpt_model_path = self._configured_or_kaggle_path(
            self.remote_gpt_model_path,
            model_info.get("gpt_model_path", ""),
        )
        sovits_model_path = self._configured_or_kaggle_path(
            self.remote_sovits_model_path,
            model_info.get("sovits_model_path", ""),
        )
        if not gpt_model_path or not sovits_model_path:
            raise RuntimeError(
                "Kaggle GPT-SoVITS weight switch requires /kaggle/... model paths. "
                "Fill the Kaggle GPT/SoVITS paths in adapter extras, or disable switch_weights."
            )
        super().switch_model({
            "gpt_model_path": gpt_model_path,
            "sovits_model_path": sovits_model_path,
        })

    def generate_speech(self, text, file_path=None, **kwargs):
        kwargs = dict(kwargs)
        ref_audio_path = self._configured_or_kaggle_path(
            self.remote_ref_audio_path,
            kwargs.get("ref_audio_path", ""),
        )
        if not ref_audio_path:
            print(
                "Kaggle GPT-SoVITS requires a /kaggle/... reference audio path. "
                "Fill remote_ref_audio_path in the TTS extra settings."
            )
            return None
        kwargs["ref_audio_path"] = ref_audio_path
        kwargs["text_split_method"] = self.text_split_method
        kwargs["batch_size"] = self.batch_size
        kwargs["speed_factor"] = kwargs.get("speed_factor") if self.use_character_speed else self.speed_factor
        if kwargs["speed_factor"] is None:
            kwargs["speed_factor"] = self.speed_factor
        kwargs["parallel_infer"] = self.parallel_infer
        kwargs["split_bucket"] = self.split_bucket
        kwargs["batch_threshold"] = self.batch_threshold
        kwargs["super_sampling"] = self.super_sampling
        return super().generate_speech(text, file_path=file_path, **kwargs)


class IndexTTSAdapter(TTSAdapter):
    """
    Adapter for a hypothetical Index TTS service.
    This demonstrates how a new service can be integrated.
    """
    STARTUP_TIMEOUT_SECONDS = 600.0
    STARTUP_POLL_INTERVAL_SECONDS = 0.5

    def __init__(
        self,
        index_server_url="http://localhost:9880/",
        index_server_work_path=None,
        tts_server_url=None,
        gpt_sovits_work_path=None,
    ):
        self.index_server_url = (tts_server_url or index_server_url).rstrip("/") + "/"
        self.current_model = None
        self._server_process = None
        self._session = requests.Session()
        if _is_local_server_url(self.index_server_url):
            # Loopback services must not be routed through HTTP(S)_PROXY.
            self._session.trust_env = False

        self.gpt_sovits_work_path = _tts_work_path(
            index_server_work_path or gpt_sovits_work_path
        )

        # Load the model and start the server process here
        self._start_server_process()

    def stop_server(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None

    def _server_is_reachable(self) -> bool:
        try:
            response = self._session.get(self.index_server_url, timeout=5)
            return response.status_code < 500
        except requests.RequestException:
            return False

    def _is_local_server_url(self) -> bool:
        return _is_local_server_url(self.index_server_url)

    def wait_until_ready(
        self,
        timeout_seconds: float | None = None,
        *,
        poll_interval_seconds: float | None = None,
    ) -> None:
        _wait_for_http_service_ready(
            self._server_is_reachable,
            service_name="IndexTTS",
            process=self._server_process,
            timeout_seconds=self.STARTUP_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds,
            poll_interval_seconds=(
                self.STARTUP_POLL_INTERVAL_SECONDS
                if poll_interval_seconds is None
                else poll_interval_seconds
            ),
        )

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        if self._server_is_reachable():
            print("IndexTTS server is already running.")
            return
        if not self._is_local_server_url():
            print("Remote IndexTTS server is not reachable; skip local auto-start.")
            return
        print("IndexTTS server not found, attempting to start...")

        if not self.gpt_sovits_work_path:
            raise RuntimeError("Local IndexTTS server is not reachable; set the IndexTTS startup path.")

        os_path = require_directory_without_links(
            self.gpt_sovits_work_path,
            field="IndexTTS work directory",
        )
        embedded_python_path = _local_python_path(
            os_path,
            service_name="IndexTTS",
        )
        raw_api_path = os_path / "api_v2.py"
        if not os.path.lexists(raw_api_path):
            raise FileNotFoundError(
                f"IndexTTS api_v2.py not found: {raw_api_path}"
            )
        api_path = require_regular_file_without_links(
            raw_api_path,
            field="IndexTTS startup script",
        )

        self._server_process = _popen_local_python_service(
            service_name="IndexTTS",
            work_root=os_path,
            python_path=embedded_python_path,
            script_path=api_path,
        )
        print("IndexTTS server starting...")

    def generate_speech(self, text, file_path=None, **kwargs):
        """Generates speech using the Index TTS API."""
        try:
            params = {
                "text": text,
                "model_id": self.current_model,
                "voice_name": kwargs.get("voice_name", "default"),
                "language": kwargs.get("text_lang", "ja")
            }
            response = self._session.post(self.index_server_url + "generate", json=params)
            response.raise_for_status()

            output = _tts_output_path(file_path, "index_tts")
            atomic_write_bytes(output, response.content)

            return output.as_posix()
        except Exception as e:
            print(f"Index TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        """Switches the model for the Index TTS service."""
        model_id = model_info.get("model_id")
        if model_id and self.current_model != model_id:
            print(f"Switching to Index TTS model: {model_id}")
            # You can add a check or call an API endpoint here to verify the model
            self.current_model = model_id

class CosyVoiceAdapter(TTSAdapter):
    """
    Adapter for the CosyVoice (Alibaba Cloud) TTS service.
    """
    def __init__(self, api_key: str = "", model: str = "cosyvoice-v2", voice: str = "longxiaochun_v2", **_ignored):
        self.api_key = str(api_key or "").strip()
        self.current_model = str(model or "cosyvoice-v2").strip() or "cosyvoice-v2"
        self.current_voice = str(voice or "longxiaochun_v2").strip() or "longxiaochun_v2"

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_key": {
                "label": "CosyVoice API Key",
                "default": "",
                "secret": True,
                "type": "str",
            },
            "model": {
                "label": "CosyVoice 模型",
                "type": "str",
                "default": "cosyvoice-v2",
            },
            "voice": {
                "label": "CosyVoice 音色",
                "type": "str",
                "default": "longxiaochun_v2",
            },
        }

    def generate_speech(self, text, file_path=None, **kwargs):
        """
        Generates TTS audio using the CosyVoice API.
        The kwargs can include 'model', 'voice', etc.
        """
        # Note: This is a simplified example. In a real-world scenario, you
        # would use the official SDK or follow the API documentation precisely.
        if not self.api_key:
            print("CosyVoice API key is empty.")
            return None
        api_url = "https://dashscope.aliyuncs.com/api/v1/tts/cosyvoice"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        params = {
            "model": kwargs.get("model", self.current_model),
            "voice": kwargs.get("voice", self.current_voice),
            "text": text
        }

        try:
            response = requests.post(api_url, headers=headers, json=params)
            response.raise_for_status()

            output = _tts_output_path(file_path, "cosyvoice")
            atomic_write_bytes(output, response.content)

            return output.as_posix()
        except Exception as e:
            print(f"CosyVoice TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        """
        Switches the voice and model for the CosyVoice service.
        `model_info` is expected to be a dictionary with 'voice' and 'model' keys.
        """
        voice = model_info.get("voice")
        model = model_info.get("model")

        if voice:
            self.current_voice = voice
            print(f"CosyVoice voice switched to: {self.current_voice}")
        if model:
            self.current_model = model
            print(f"CosyVoice model switched to: {self.current_model}")

class GenieTTSAdapter(TTSAdapter):
    """
    Adapter for the Genie TTS service.
    Encapsulates the logic for loading character models, setting references, and generating speech.
    """
    def __init__(
        self,
        tts_server_url="http://127.0.0.1:9880/",
        tts_work_path=None,
        gpt_sovits_work_path=None
    ):
        self.tts_server_url = tts_server_url.rstrip("/") + "/"
        # Keep compatibility with existing factory argument name.
        self.tts_work_path = _tts_work_path(tts_work_path or gpt_sovits_work_path)
        self.character_name = None
        self.onnx_model_dir = None
        self.loaded_character_name = None
        self.reference_audio_key = None
        self._server_process = None
        self._start_server_process()

    def stop_server(self) -> None:
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=5)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None

    @staticmethod
    def _encode_name(name: str) -> str:
        if not name:
            return ""
        # Remove '=' padding to keep folder names shorter and cleaner.
        encoded = (
            base64.urlsafe_b64encode(name.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )
        try:
            return safe_path_component(encoded, field="Genie character key")
        except ValueError:
            # Base64 expands arbitrary Unicode names by roughly one third. A
            # character name that is itself a valid 255-byte component can
            # therefore become an invalid ONNX directory/key after encoding.
            # Preserve every existing short key and fit only the previously
            # unusable edge case, retaining a digest so distinct long names do
            # not collapse onto the same truncated prefix.
            digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
            return safe_path_component_with_suffix(
                encoded,
                f"-{digest}",
                field="Genie character key",
            )

    def _resolve_converter_script(self):
        if not self.tts_work_path:
            return None
        base_path = require_symlink_free_absolute_path(
            self.tts_work_path,
            field="Genie TTS work path",
        )
        if base_path.suffix.lower() == ".py":
            if not os.path.lexists(base_path):
                return None
            return require_regular_file_without_links(
                base_path,
                field="Genie TTS converter script",
            )
        base_path = require_directory_without_links(
            base_path,
            field="Genie TTS work directory",
        )
        candidates = [base_path / "convert.py", base_path / "convery.py"]
        for script in candidates:
            if os.path.lexists(script):
                return require_regular_file_without_links(
                    script,
                    field="Genie TTS converter script",
                )
        return None

    def _has_onnx_files(self, onnx_dir: str) -> bool:
        if not onnx_dir:
            return False
        try:
            onnx_path = require_directory_without_links(
                onnx_dir,
                field="Genie ONNX model directory",
            )
        except (FileNotFoundError, NotADirectoryError):
            return False
        _, files = inspect_portable_directory_tree(onnx_path)
        return any(candidate.suffix.lower() == ".onnx" for candidate in files)

    def _convert_model_to_onnx(self, character_name: str, ckpt_model_path: str, pth_model_path: str, onnx_dir: str):
        root = project_root()
        ckpt_path = resolve_runtime_asset_read_path(ckpt_model_path, root=root)
        pth_path = resolve_runtime_asset_read_path(pth_model_path, root=root)
        output_dir = resolve_project_output_path(onnx_dir, root=root)
        ckpt_snapshot = capture_launch_file(
            ckpt_path,
            field="Genie checkpoint input",
        )
        pth_snapshot = capture_launch_file(
            pth_path,
            field="Genie model input",
        )

        converter_script = self._resolve_converter_script()
        if converter_script is None:
            raise FileNotFoundError("Cannot find convert.py/convery.py in tts_work_path.")

        work_path = converter_script.parent
        embedded_python_path = _bundled_python_path(work_path)
        if embedded_python_path is None:
            raise FileNotFoundError(f"Bundled runtime Python not found under: {work_path}")
        work_snapshot = capture_launch_directory(
            work_path,
            field="Genie converter working directory",
        )
        python_snapshot = capture_launch_file(
            embedded_python_path,
            field="Genie converter Python executable",
            executable=True,
        )
        converter_snapshot = capture_launch_file(
            converter_script,
            field="Genie converter script",
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = require_directory_without_links(
            output_dir,
            field="Genie ONNX output directory",
        )
        output_snapshot = capture_launch_directory(
            output_dir,
            field="Genie ONNX output directory",
        )
        cmd = [
            str(python_snapshot.path),
            str(converter_snapshot.path),
            "--pth", pth_snapshot.path.as_posix(),
            "--ckpt", ckpt_snapshot.path.as_posix(),
            "--out", output_dir.as_posix(),
        ]
        print(f"Converting ONNX for '{character_name}' ...")
        result = run_with_stable_paths(
            cmd,
            cwd=work_snapshot,
            executable=python_snapshot,
            required_directories=(output_snapshot,),
            required_files=(
                converter_snapshot,
                pth_snapshot,
                ckpt_snapshot,
            ),
            env=isolated_python_environment(),
            run_factory=subprocess.run,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Convert failed (code={result.returncode}).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        print(f"ONNX convert finished for '{character_name}': {output_dir}")

    def _is_valid_wav_file(
        self,
        file_path: str,
        *,
        expected_identity: os.stat_result | None = None,
        expected_parent_identity: os.stat_result | None = None,
    ) -> bool:
        if not file_path:
            return False
        try:
            with (
                open_binary_read_without_links(
                    file_path,
                    expected_identity=expected_identity,
                    expected_parent_identity=expected_parent_identity,
                ) as source,
                wave.open(source, "rb") as wav_f,
            ):
                before = os.fstat(source.fileno())
                # Trigger parsing.
                wav_f.getnchannels()
                wav_f.getframerate()
                wav_f.getnframes()
                after = os.fstat(source.fileno())
                if not file_snapshot_is_stable(before, after):
                    return False
            return True
        except Exception:
            return False

    def _write_raw_stream_as_wav(
        self,
        raw_bytes: bytes,
        out_path: str,
        sample_rate: int = 32000,
        *,
        expected_parent_identity: os.stat_result | None = None,
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
                        for x in float_arr:
                            if not math.isfinite(x):
                                x = 0.0
                            if x > 1.0:
                                x = 1.0
                            elif x < -1.0:
                                x = -1.0
                            pcm_i16.append(int(x * 32767.0))
                        pcm_bytes = pcm_i16.tobytes()
            except Exception:
                pcm_bytes = b""

        # Case 2: int16 PCM stream
        if not pcm_bytes and len(raw_bytes) % 2 == 0:
            pcm_bytes = raw_bytes

        if not pcm_bytes:
            return False

        try:
            written_identity: os.stat_result | None = None
            with atomic_binary_writer(
                out_path,
                expected_parent_identity=expected_parent_identity,
            ) as output:
                with wave.open(output, "wb") as wav_f:
                    wav_f.setnchannels(1)
                    wav_f.setsampwidth(2)
                    wav_f.setframerate(sample_rate)
                    wav_f.writeframes(pcm_bytes)
                written_identity = os.fstat(output.fileno())
            output_identity = Path(out_path).lstat()
            if (
                written_identity is None
                or not os.path.samestat(written_identity, output_identity)
            ):
                return False
            return self._is_valid_wav_file(
                out_path,
                expected_identity=written_identity,
                expected_parent_identity=expected_parent_identity,
            )
        except Exception:
            return False

    def _write_pcm_chunks_as_wav(
        self,
        chunks,
        out_path: str,
        sample_rate: int = 32000,
        *,
        expected_parent_identity: os.stat_result | None = None,
    ) -> bool:
        try:
            written_identity: os.stat_result | None = None
            with atomic_binary_writer(
                out_path,
                expected_parent_identity=expected_parent_identity,
            ) as output:
                with wave.open(output, "wb") as wav_f:
                    wav_f.setnchannels(1)
                    wav_f.setsampwidth(2)
                    wav_f.setframerate(sample_rate)
                    for chunk in chunks:
                        if chunk:
                            wav_f.writeframesraw(chunk)
                written_identity = os.fstat(output.fileno())
            output_identity = Path(out_path).lstat()
            if (
                written_identity is None
                or not os.path.samestat(written_identity, output_identity)
            ):
                return False
            return self._is_valid_wav_file(
                out_path,
                expected_identity=written_identity,
                expected_parent_identity=expected_parent_identity,
            )
        except Exception:
            return False

    def _start_server_process(self):
        """Starts the Genie TTS server process if it isn't running."""
        if self._is_server_alive():
            print("Genie TTS server is already running.")
            return

        if not self.tts_work_path:
            raise RuntimeError("Local Genie TTS server is not reachable; set the Genie TTS startup path.")

        os_path = require_symlink_free_absolute_path(
            self.tts_work_path,
            field="Genie TTS work path",
        )
        if os_path.suffix.lower() == ".py":
            os_path = os_path.parent
        os_path = require_directory_without_links(
            os_path,
            field="Genie TTS work directory",
        )

        embedded_python_path = _bundled_python_path(os_path)
        raw_start_script_path = os_path / "start.py"

        if embedded_python_path is None:
            print(f"Genie TTS bundled runtime Python not found under: {os_path}")
            return
        if not os.path.lexists(raw_start_script_path):
            print(f"Genie TTS start.py not found: {raw_start_script_path}")
            return
        start_script_path = require_regular_file_without_links(
            raw_start_script_path,
            field="Genie TTS startup script",
        )

        self._server_process = _popen_local_python_service(
            service_name="Genie TTS",
            work_root=os_path,
            python_path=embedded_python_path,
            script_path=start_script_path,
        )
        print("Genie TTS server starting...")
        for _ in range(20):
            time.sleep(0.5)
            if self._is_server_alive():
                print("Genie TTS server started successfully.")
                return
        print("Genie TTS server start timeout, continue and retry on request.")

    def _is_server_alive(self):
        try:
            response = requests.post(self.tts_server_url + "stop", timeout=1.5)
            return response.status_code in (200, 204, 405)
        except Exception:
            return False

    def _load_character_model(self, language="ja"):
        """Load the character model via Genie TTS HTTP API."""
        if not self.character_name or not self.onnx_model_dir:
            print("Genie TTS switch_model missing character_name/onnx_model_dir.")
            return
        if not self._has_onnx_files(self.onnx_model_dir):
            raise FileNotFoundError(
                f"Genie TTS model directory has no safe ONNX files: {self.onnx_model_dir}"
            )
        try:
            encoded_character_name = self._encode_name(self.character_name)
            payload = {
                "character_name": encoded_character_name,
                "onnx_model_dir": self.onnx_model_dir,
                "language": language
            }
            response = requests.post(self.tts_server_url + "load_character", json=payload, timeout=20)
            response.raise_for_status()
            self.loaded_character_name = self.character_name
            print(f"Genie TTS character '{self.character_name}' loaded successfully.")
        except Exception as e:
            print(f"Failed to load Genie TTS character model: {e}")
            raise

    def generate_speech(self, text, file_path=None, **kwargs):
        """
        Generates TTS audio using the Genie TTS engine.

        Args:
            text (str): The text to synthesize.
            file_path (str, optional): The path to save the generated audio.
            **kwargs: Extra arguments, including 'ref_audio_path' and 'audio_text'.

        Returns:
            str: The absolute path of the generated audio file, or None on failure.
        """
        runtime_character_name = kwargs.get("character_name")
        if runtime_character_name and runtime_character_name != self.character_name:
            self.character_name = runtime_character_name

        if not self.character_name:
            print("Genie TTS has no active character. Call switch_model first.")
            return None

        ref_audio_path = kwargs.get('ref_audio_path')
        audio_text = kwargs.get('prompt_text')
        audio_lang = kwargs.get('prompt_lang') or kwargs.get('text_lang') or "zh"
        print(f"Genie TTS generate_speech called with character='{self.character_name}', audio_lang='{audio_lang}'")
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
                    "language": audio_lang
                }
                response = requests.post(self.tts_server_url + "set_reference_audio", json=payload, timeout=20)
                response.raise_for_status()
                self.reference_audio_key = reference_audio_key
                print("Genie TTS reference audio set successfully.")
            except Exception as e:
                print(f"Failed to set Genie TTS reference audio: {e}")

        try:
            output = _tts_output_path(file_path, "genie_tts")
            output_parent, output_parent_identity = capture_directory_identity(
                output.parent,
                field="Genie TTS output directory",
            )
            if output.parent != output_parent:
                raise PermissionError("Genie TTS output directory changed identity")
            abs_file_path = output.as_posix()
            print(f"Genie TTS save path: {abs_file_path}")
            payload = {
                "character_name": encoded_character_name,
                "text": text,
                "split_sentence": False,
            }
            with requests.post(self.tts_server_url + "tts", json=payload, stream=True, timeout=120) as response:
                response.raise_for_status()
                chunks = [chunk for chunk in response.iter_content(chunk_size=4096) if chunk]

            if not chunks:
                print("Genie TTS returned empty audio stream.")
                return None

            first_bytes = chunks[0][:16]
            is_riff = first_bytes[:4] == b"RIFF"
            if is_riff:
                written_identity: os.stat_result | None = None
                with atomic_binary_writer(
                    abs_file_path,
                    expected_parent_identity=output_parent_identity,
                ) as f:
                    for chunk in chunks:
                        f.write(chunk)
                    written_identity = os.fstat(f.fileno())
                output_identity = output.lstat()
                if (
                    written_identity is None
                    or not os.path.samestat(written_identity, output_identity)
                    or not self._is_valid_wav_file(
                        abs_file_path,
                        expected_identity=written_identity,
                        expected_parent_identity=output_parent_identity,
                    )
                ):
                    print(
                        "Genie TTS did not create a stable valid WAV file: "
                        f"{abs_file_path}"
                    )
                    return None
            else:
                # Official sample streams raw PCM bytes to PyAudio directly.
                # Here we encapsulate raw PCM into a standard WAV file for pygame playback.
                if not self._write_pcm_chunks_as_wav(
                    chunks,
                    abs_file_path,
                    sample_rate=32000,
                    expected_parent_identity=output_parent_identity,
                ):
                    raw_bytes = b"".join(chunks)
                    if not self._write_raw_stream_as_wav(
                        raw_bytes,
                        abs_file_path,
                        sample_rate=32000,
                        expected_parent_identity=output_parent_identity,
                    ):
                        print("Genie TTS output is not valid WAV and conversion failed.")
                        return None
            require_directory_identity(
                output_parent,
                output_parent_identity,
                field="Genie TTS output directory",
            )

            print("Genie TTS audio generation complete.")
            return abs_file_path
        except Exception as e:
            print(f"Genie TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        """
        For Genie TTS, this method can be used to switch characters or reload the model.
        `model_info` is expected to have 'character_name' and 'onnx_model_dir'.
        """
        if model_info is None:
            print("Genie TTS switch_model got empty model_info.")
            return
        new_character_name = model_info.get("character_name") or model_info.get("name")
        ckpt_model_path = model_info.get("gpt_model_path")
        pth_model_path = model_info.get("sovits_model_path")
        new_onnx_model_dir = model_info.get("onnx_model_dir")
        encoded_character_name = self._encode_name(new_character_name) if new_character_name else ""

        if not new_onnx_model_dir and encoded_character_name:
            new_onnx_model_dir = str(
                managed_project_directory(
                    "onnx",
                    encoded_character_name,
                    root=project_root(),
                )
            )
        elif new_onnx_model_dir:
            raw_onnx_dir = str(new_onnx_model_dir)
            new_onnx_model_dir = str(
                resolve_runtime_asset_read_path(
                    raw_onnx_dir,
                    root=project_root(),
                    resource_prefixes=(),
                )
            )

        if new_onnx_model_dir and not self._has_onnx_files(new_onnx_model_dir):
            if ckpt_model_path and pth_model_path:
                try:
                    self._convert_model_to_onnx(
                        character_name=new_character_name or "unknown",
                        ckpt_model_path=ckpt_model_path,
                        pth_model_path=pth_model_path,
                        onnx_dir=new_onnx_model_dir
                    )
                except Exception as e:
                    raise RuntimeError(f"Auto convert ONNX failed: {e}") from e
            else:
                raise FileNotFoundError(
                    "Genie TTS model directory has no safe ONNX files and no "
                    "ckpt/pth source paths were provided"
                )
            if not self._has_onnx_files(new_onnx_model_dir):
                raise FileNotFoundError(
                    "Genie TTS conversion completed without producing a safe ONNX file"
                )

        if new_onnx_model_dir and self.onnx_model_dir != new_onnx_model_dir:
            self.onnx_model_dir = new_onnx_model_dir
            self.loaded_character_name = None

        if new_character_name and self.character_name != new_character_name:
            self.character_name = new_character_name
            self.loaded_character_name = None

        if self.character_name and self.onnx_model_dir and self.loaded_character_name != self.character_name:
            print(f"Switching Genie TTS character to: {self.character_name}")
            self._load_character_model()

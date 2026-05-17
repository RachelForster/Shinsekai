# tts_adapter.py
from sdk.adapters import TTSAdapter
import os
import requests
import threading
import queue
import base64
import math
import wave
import array
import re
import sys
from pathlib import Path
import subprocess
import time
from typing import Optional, Callable


def _coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class GPTSoVitsAdapter(TTSAdapter):
    """
    Adapter for the GPT-SoVITS TTS service.
    It adapts the GPT-SoVITS API to the standard TTSAdapter interface.
    """
    def __init__(
        self,
        tts_server_url="http://127.0.0.1:9880/",
        gpt_sovits_work_path=None,
        top_k: int = 15,
        top_p: float = 1,
        temperature: float = 1,
        repetition_penalty: float = 1.35,
        sample_steps: int = 32,
        batch_threshold: float = 0.75,
        fragment_interval: float = 0.3,
        text_split_method: str = "cut5",
        parallel_infer: bool = False,
        split_bucket: bool = False,
        super_sampling: bool = True,
        clarity_filter_enabled: bool = True,
        clarity_boost: float = 0.35,
        normalize_peak: float = 0.92,
        timeout_seconds: int = 180,
        **kwargs,
    ):
        self.tts_server_url = str(tts_server_url or "http://127.0.0.1:9880/")
        if not self.tts_server_url.endswith("/"):
            self.tts_server_url += "/"
        self.sovits_model_path = ''
        self.gpt_model_path = ''
        self.gpt_sovits_work_path = str(gpt_sovits_work_path) if gpt_sovits_work_path else None
        self._server_process = None
        self.top_k = int(top_k or 15)
        self.top_p = float(top_p or 1)
        self.temperature = float(temperature or 1)
        self.repetition_penalty = float(repetition_penalty or 1.35)
        self.sample_steps = int(sample_steps or 32)
        self.batch_threshold = float(batch_threshold or 0.75)
        self.fragment_interval = float(fragment_interval or 0.3)
        self.text_split_method = str(text_split_method or "cut5")
        self.parallel_infer = _coerce_bool(parallel_infer, False)
        self.split_bucket = _coerce_bool(split_bucket, False)
        self.super_sampling = _coerce_bool(super_sampling, True)
        self.clarity_filter_enabled = _coerce_bool(clarity_filter_enabled, True)
        self.clarity_boost = max(0.0, min(1.0, float(clarity_boost or 0.35)))
        self.normalize_peak = max(0.1, min(0.99, float(normalize_peak or 0.92)))
        self.timeout_seconds = int(timeout_seconds or 180)

        # Consider the user's input mistake
        if self.gpt_sovits_work_path and self.gpt_sovits_work_path.endswith(".py"):
            self.gpt_sovits_work_path = Path(self.gpt_sovits_work_path).parent.as_posix()


        # Load the model and start the server process here
        self._start_server_process()

    @classmethod
    def get_config_schema(cls) -> dict:
        return {
            "top_k": {"type": "int", "label": "Top K", "default": 15, "min": 1, "max": 100},
            "top_p": {"type": "float", "label": "Top P", "default": 1, "min": 0.1, "max": 1.0},
            "temperature": {"type": "float", "label": "Temperature", "default": 1, "min": 0.1, "max": 2.0},
            "repetition_penalty": {
                "type": "float",
                "label": "Repetition penalty",
                "default": 1.35,
                "min": 0.8,
                "max": 2.0,
            },
            "sample_steps": {"type": "int", "label": "Sample steps", "default": 32, "min": 4, "max": 64},
            "batch_threshold": {
                "type": "float",
                "label": "Batch threshold",
                "default": 0.75,
                "min": 0.1,
                "max": 1.0,
            },
            "fragment_interval": {
                "type": "float",
                "label": "Fragment interval",
                "default": 0.3,
                "min": 0.0,
                "max": 1.0,
            },
            "text_split_method": {
                "type": "str",
                "label": "Text split method",
                "default": "cut5",
            },
            "timeout_seconds": {
                "type": "int",
                "label": "Timeout seconds",
                "default": 180,
                "min": 30,
                "max": 600,
            },
            "parallel_infer": {
                "type": "bool",
                "label": "Parallel infer",
                "default": False,
            },
            "split_bucket": {
                "type": "bool",
                "label": "Split bucket",
                "default": False,
            },
            "super_sampling": {
                "type": "bool",
                "label": "Super sampling",
                "default": True,
            },
            "clarity_filter_enabled": {
                "type": "bool",
                "label": "Clarity filter",
                "default": True,
            },
            "clarity_boost": {
                "type": "float",
                "label": "Clarity boost",
                "default": 0.35,
                "min": 0.0,
                "max": 1.0,
            },
            "normalize_peak": {
                "type": "float",
                "label": "Normalize peak",
                "default": 0.92,
                "min": 0.1,
                "max": 0.99,
            },
        }

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

    def _server_is_reachable(self) -> bool:
        try:
            response = requests.get(self.tts_server_url + "docs", timeout=2)
            return response.status_code < 500
        except requests.exceptions.RequestException:
            return False

    def _wait_for_server(self, timeout_seconds: int = 90) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._server_is_reachable():
                return True
            time.sleep(1)
        return False

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        if self._server_is_reachable():
            print("GPT-SoVITS server is already running.")
            return

        print("GPT-SoVITS server not found, attempting to start...")

        if self.gpt_sovits_work_path is None:
            return

        os_path = self.gpt_sovits_work_path
        embeded_python_path = os.path.join(os_path, "runtime", "python.exe")
        api_path = os.path.join(os_path, "api_v2.py")
        
        # Use subprocess.Popen to start the server in the background
        self._server_process = subprocess.Popen([embeded_python_path, api_path], cwd=os_path)
        print("GPT-SoVITS server starting...")
        if self._wait_for_server():
            print("GPT-SoVITS server is ready.")
        else:
            print("GPT-SoVITS server is still starting; first speech may need a moment.")

    def _post_process_wav(self, file_path: str) -> None:
        if not self.clarity_filter_enabled or not str(file_path).lower().endswith(".wav"):
            return
        try:
            with wave.open(file_path, "rb") as source:
                params = source.getparams()
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                frames = source.readframes(source.getnframes())

            if sample_width != 2 or not frames:
                return

            samples = array.array("h")
            samples.frombytes(frames)
            if sys.byteorder == "big":
                samples.byteswap()

            processed = array.array("h")
            lowpass = [0.0] * max(1, channels)
            alpha = 0.10
            boost = self.clarity_boost
            for index, sample in enumerate(samples):
                channel = index % channels
                lowpass[channel] = lowpass[channel] + alpha * (float(sample) - lowpass[channel])
                high_band = float(sample) - lowpass[channel]
                value = float(sample) + boost * high_band
                processed.append(max(-32768, min(32767, int(value))))

            peak = max((abs(sample) for sample in processed), default=0)
            target_peak = int(32767 * self.normalize_peak)
            if peak > 0 and target_peak > 0:
                gain = min(1.8, target_peak / peak)
                processed = array.array(
                    "h",
                    (max(-32768, min(32767, int(sample * gain))) for sample in processed),
                )

            if sys.byteorder == "big":
                processed.byteswap()

            with wave.open(file_path, "wb") as output:
                output.setparams(params)
                output.writeframes(processed.tobytes())
        except Exception as exc:
            print(f"GPT-SoVITS WAV clarity post-process skipped: {exc}")

    def generate_speech(self, text, file_path=None, **kwargs):
        """
        Generates TTS audio using the GPT-SoVITS API.
        The kwargs dictionary can include parameters like ref_audio_path, prompt_text, etc.
        """
        text = str(text or "").strip()
        if not re.search(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]", text):
            print("GPT-SoVITS TTS skipped: text has no speakable content.")
            return None

        # Parameters for the GPT-SoVITS API call
        params = {
            "ref_audio_path": kwargs.get("ref_audio_path", ""),
            "aux_ref_audio_paths": kwargs.get("aux_ref_audio_paths") or [],
            "prompt_text": kwargs.get("prompt_text", ""),
            "prompt_lang": kwargs.get("prompt_lang", ""),
            "text": text,
            "text_lang": kwargs.get("text_lang", "ja"),
            "text_split_method": kwargs.get("text_split_method", self.text_split_method),
            "batch_size": 1,
            "batch_threshold": kwargs.get("batch_threshold", self.batch_threshold),
            "split_bucket": kwargs.get("split_bucket", self.split_bucket),
            "speed_factor": kwargs.get("speed_factor", 1.0),
            "fragment_interval": kwargs.get("fragment_interval", self.fragment_interval),
            "seed": kwargs.get("seed", -1),
            "media_type": "wav",
            "streaming_mode": False,
            "parallel_infer": kwargs.get("parallel_infer", self.parallel_infer),
            "top_k": kwargs.get("top_k", self.top_k),
            "top_p": kwargs.get("top_p", self.top_p),
            "temperature": kwargs.get("temperature", self.temperature),
            "repetition_penalty": kwargs.get("repetition_penalty", self.repetition_penalty),
            "sample_steps": kwargs.get("sample_steps", self.sample_steps),
            "super_sampling": kwargs.get("super_sampling", self.super_sampling),
        }

        try:
            response = requests.post(
                self.tts_server_url + "tts",
                json=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status() # Raise an exception for bad status codes

            if not file_path:
                # Logic to create a temporary file path
                # ... (You can use the logic from the original tts_manager.py)
                file_path = "path_to_temporary_file.wav"

            with open(file_path, 'wb') as f:
                f.write(response.content)
            self._post_process_wav(file_path)

            return os.path.abspath(file_path)
        except Exception as e:
            print(f"GPT-SoVITS TTS generation failed: {e}")
            return None

    def switch_model(self, model_info):
        """
        Switches the GPT-SoVITS models.
        `model_info` is expected to be a dictionary with 'gpt_model_path' and 'sovits_model_path'.
        """
    
        gpt_model_path = model_info.get('gpt_model_path', '')
        sovits_model_path = model_info.get('sovits_model_path', '')
        
        if self.sovits_model_path == sovits_model_path and self.gpt_model_path == gpt_model_path:
            print("No model switch needed, current models are already set.", self.gpt_model_path, self.sovits_model_path)
            return
        
        try:
            if gpt_model_path and gpt_model_path.endswith(".ckpt"):
                response = requests.get(self.tts_server_url + "set_gpt_weights", params={"weights_path": gpt_model_path})
                response.raise_for_status()
                self.gpt_model_path = gpt_model_path
                print(f"gpt model switched successfully: {gpt_model_path}")
        except Exception as e:
            print(f"Failed to switch gpt model: {e}")

        try:
            if sovits_model_path and sovits_model_path.endswith(".pth"):
                response = requests.get(self.tts_server_url + "set_sovits_weights", params={"weights_path": sovits_model_path})
                response.raise_for_status()
                self.sovits_model_path = sovits_model_path
                print(f"sovits model switched successfully: {sovits_model_path}")
        except Exception as e:
            print(f"Failed to switch sovits model: {e}")


class IndexTTSAdapter(TTSAdapter):
    """
    Adapter for a hypothetical Index TTS service.
    This demonstrates how a new service can be integrated.
    """
    def __init__(self, index_server_url="http://localhost:9880/", index_server_work_path = None):
        self.index_server_url = index_server_url
        self.current_model = None
        self._server_process = None

        self.gpt_sovits_work_path = index_server_work_path

        # Load the model and start the server process here
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

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        try:
            # You might want to add a check here to see if the process is already running
            response = requests.get(self.index_server_url)
            if response.status_code == 200:
                print("GPT-SoVITS server is already running.")
                return
        except requests.exceptions.ConnectionError:
            print("GPT-SoVITS server not found, attempting to start...")

        if self.gpt_sovits_work_path is None:
            return

        os_path = self.gpt_sovits_work_path
        embeded_python_path = os.path.join(os_path, "runtime", "python.exe")
        api_path = os.path.join(os_path, "api_v2.py")
        
        # Use subprocess.Popen to start the server in the background
        self._server_process = subprocess.Popen([embeded_python_path, api_path], cwd=os_path)
        print("GPT-SoVITS server starting...")
    
    def generate_speech(self, text, file_path=None, **kwargs):
        """Generates speech using the Index TTS API."""
        try:
            params = {
                "text": text,
                "model_id": self.current_model,
                "voice_name": kwargs.get("voice_name", "default"),
                "language": kwargs.get("text_lang", "ja")
            }
            response = requests.post(self.index_server_url + "generate", json=params)
            response.raise_for_status()

            if not file_path:
                file_path = "path_to_index_tts_file.wav"

            with open(file_path, 'wb') as f:
                f.write(response.content)

            return os.path.abspath(file_path)
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
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.current_model = "cosyvoice-v2"  # Default model
        self.current_voice = "longxiaochun_v2" # Default voice

    def generate_speech(self, text, file_path=None, **kwargs):
        """
        Generates TTS audio using the CosyVoice API.
        The kwargs can include 'model', 'voice', etc.
        """
        # Note: This is a simplified example. In a real-world scenario, you
        # would use the official SDK or follow the API documentation precisely.
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

            if not file_path:
                file_path = "temp_cosyvoice.wav"

            with open(file_path, "wb") as f:
                f.write(response.content)

            return os.path.abspath(file_path)
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
        self.tts_work_path = tts_work_path or gpt_sovits_work_path
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
        return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")

    def _resolve_converter_script(self):
        if not self.tts_work_path:
            return None
        base_path = Path(self.tts_work_path)
        if base_path.suffix.lower() == ".py":
            return base_path if base_path.exists() else None
        candidates = [base_path / "convert.py", base_path / "convery.py"]
        for script in candidates:
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

    def _convert_model_to_onnx(self, character_name: str, ckpt_model_path: str, pth_model_path: str, onnx_dir: str):
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
            "--pth", pth_model_path,
            "--ckpt", ckpt_model_path,
            "--out", onnx_dir
        ]
        print(f"Converting ONNX for '{character_name}' ...")
        result = subprocess.run(cmd, cwd=str(work_path), capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(
                f"Convert failed (code={result.returncode}).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        print(f"ONNX convert finished for '{character_name}': {onnx_dir}")

    def _is_valid_wav_file(self, file_path: str) -> bool:
        if not file_path or not os.path.exists(file_path):
            return False
        try:
            with wave.open(file_path, "rb") as wav_f:
                # Trigger parsing.
                wav_f.getnchannels()
                wav_f.getframerate()
                wav_f.getnframes()
            return True
        except Exception:
            return False

    def _write_raw_stream_as_wav(self, raw_bytes: bytes, out_path: str, sample_rate: int = 32000) -> bool:
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
            with wave.open(out_path, "wb") as wav_f:
                wav_f.setnchannels(1)
                wav_f.setsampwidth(2)
                wav_f.setframerate(sample_rate)
                wav_f.writeframes(pcm_bytes)
            return self._is_valid_wav_file(out_path)
        except Exception:
            return False

    def _write_pcm_chunks_as_wav(self, chunks, out_path: str, sample_rate: int = 32000) -> bool:
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

    def _start_server_process(self):
        """Starts the Genie TTS server process if it isn't running."""
        if self._is_server_alive():
            print("Genie TTS server is already running.")
            return

        if not self.tts_work_path:
            print("Genie TTS work path is empty, cannot auto start server.")
            return

        os_path = self.tts_work_path
        if os_path.endswith(".py"):
            os_path = str(Path(os_path).parent)

        embedded_python_path = os.path.join(os_path, "runtime", "python.exe")
        start_script_path = os.path.join(os_path, "start.py")

        if not os.path.exists(embedded_python_path):
            print(f"Genie TTS runtime not found: {embedded_python_path}")
            return
        if not os.path.exists(start_script_path):
            print(f"Genie TTS start.py not found: {start_script_path}")
            return

        self._server_process = subprocess.Popen([embedded_python_path, start_script_path], cwd=os_path)
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
            if not file_path:
                file_path = os.path.join("temp", f"genie_tts_{os.urandom(4).hex()}.wav")

            abs_file_path = os.path.abspath(file_path)
            print(f"Genie TTS save path: {abs_file_path}")
            os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
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
                with open(abs_file_path, "wb") as f:
                    for chunk in chunks:
                        f.write(chunk)
            else:
                # Official sample streams raw PCM bytes to PyAudio directly.
                # Here we encapsulate raw PCM into a standard WAV file for pygame playback.
                if not self._write_pcm_chunks_as_wav(chunks, abs_file_path, sample_rate=32000):
                    raw_bytes = b"".join(chunks)
                    if not self._write_raw_stream_as_wav(raw_bytes, abs_file_path, sample_rate=32000):
                        print("Genie TTS output is not valid WAV and conversion failed.")
                        return None

            if not os.path.exists(abs_file_path):
                print(f"Genie TTS did not create output file: {abs_file_path}")
                return None

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
            new_onnx_model_dir = str((Path("onnx") / encoded_character_name).resolve())

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
                    print(f"Auto convert ONNX failed: {e}")
            else:
                print("ONNX dir missing and no ckpt/pth path provided.")

        if new_onnx_model_dir and self.onnx_model_dir != new_onnx_model_dir:
            self.onnx_model_dir = new_onnx_model_dir
            self.loaded_character_name = None

        if new_character_name and self.character_name != new_character_name:
            self.character_name = new_character_name
            self.loaded_character_name = None

        if self.character_name and self.onnx_model_dir and self.loaded_character_name != self.character_name:
            print(f"Switching Genie TTS character to: {self.character_name}")
            self._load_character_model()

# tts_adapter.py
from abc import ABC, abstractmethod
import os
import requests
import threading
import queue
from pathlib import Path
import subprocess
import time
from typing import Optional, Callable

class TTSAdapter(ABC):
    """
    Abstract Adapter for TTS services.
    This defines the standard interface that all TTS adapters must implement.
    """
    @abstractmethod
    def generate_speech(self, text, file_path=None, **kwargs):
        """Generates speech from text and returns the file path."""
        pass

    @abstractmethod
    def switch_model(self, model_info):
        """Switches the TTS model."""
        pass

class GPTSoVitsAdapter(TTSAdapter):
    """
    Adapter for the GPT-SoVITS TTS service.
    It adapts the GPT-SoVITS API to the standard TTSAdapter interface.
    """
    def __init__(self, tts_server_url="http://127.0.0.1:9880/", gpt_sovits_work_path = None):
        self.tts_server_url = tts_server_url
        self.sovits_model_path = ''
        self.gpt_model_path = ''
        self.gpt_sovits_work_path = gpt_sovits_work_path

        # Consider the user's input mistake
        if self.gpt_sovits_work_path.endswith(".py"):
            self.gpt_sovits_work_path = Path(self.gpt_sovits_work_path).parent.as_posix()
        

        # Load the model and start the server process here
        self._start_server_process()

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        try:
            # You might want to add a check here to see if the process is already running
            response = requests.get(self.tts_server_url)
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
        subprocess.Popen([embeded_python_path, api_path], cwd=os_path)
        print("GPT-SoVITS server starting...")

    def generate_speech(self, text, file_path=None, **kwargs):
        """
        Generates TTS audio using the GPT-SoVITS API.
        The kwargs dictionary can include parameters like ref_audio_path, prompt_text, etc.
        """

        # Parameters for the GPT-SoVITS API call
        params = {
            "ref_audio_path": kwargs.get("ref_audio_path", ""),
            "prompt_text": kwargs.get("prompt_text", ""),
            "prompt_lang": kwargs.get("prompt_lang", ""),
            "text": text,
            "text_lang": kwargs.get("text_lang", "ja"),
            "text_split_method": "cut5",
            "batch_size": 1,
            "speed_factor": kwargs.get("speed_factor", 1.4),
        }

        try:
            response = requests.post(self.tts_server_url + "tts", json=params)
            response.raise_for_status() # Raise an exception for bad status codes

            if not file_path:
                # Logic to create a temporary file path
                # ... (You can use the logic from the original tts_manager.py)
                file_path = "path_to_temporary_file.wav"

            with open(file_path, 'wb') as f:
                f.write(response.content)

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

        self.gpt_sovits_work_path = index_server_work_path

        # Load the model and start the server process here
        self._start_server_process()

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
        subprocess.Popen([embeded_python_path, api_path], cwd=os_path)
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
        self._start_server_process()

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

        subprocess.Popen([embedded_python_path, start_script_path], cwd=os_path)
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

    def _load_character_model(self):
        """Load the character model via Genie TTS HTTP API."""
        if not self.character_name or not self.onnx_model_dir:
            print("Genie TTS switch_model missing character_name/onnx_model_dir.")
            return
        try:
            payload = {
                "character_name": self.character_name,
                "onnx_model_dir": self.onnx_model_dir,
                "language": "zh"
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
        
        if self.loaded_character_name != self.character_name:
            self._load_character_model()

        ref_audio_path = kwargs.get('ref_audio_path')
        audio_text = kwargs.get('prompt_text')
        audio_lang = kwargs.get('prompt_lang') or kwargs.get('text_lang') or "zh"
        reference_audio_key = f"{ref_audio_path}|{audio_text}|{audio_lang}"

        if ref_audio_path and audio_text and self.reference_audio_key != reference_audio_key:
            try:
                payload = {
                    "character_name": self.character_name,
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

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            payload = {
                "character_name": self.character_name,
                "text": text,
                "split_sentence": False,
                "save_path": file_path
            }
            response = requests.post(self.tts_server_url + "tts", json=payload, timeout=90)
            response.raise_for_status()

            # If server returns stream, write it. If server writes directly to save_path, keep existing file.
            if response.content and len(response.content) > 44:
                with open(file_path, 'wb') as f:
                    f.write(response.content)

            if not os.path.exists(file_path):
                print(f"Genie TTS did not create output file: {file_path}")
                return None

            print("Genie TTS audio generation complete.")
            return os.path.abspath(file_path)
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

        if not new_onnx_model_dir and new_character_name:
            new_onnx_model_dir = str((Path("onnx") / new_character_name).resolve())

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
# tts_adapter.py
from abc import ABC, abstractmethod
import os
import requests
import threading
import queue
import subprocess
from typing import Optional, Callable

from abc import ABC, abstractmethod

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
    def __init__(self, tts_server_url="http://127.0.0.1:9880/"):
        self.tts_server_url = tts_server_url
        self.sovits_model_path = ''
        self.gpt_model_path = ''

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
            return

        self.sovits_model_path = sovits_model_path
        self.gpt_model_path = gpt_model_path
        
        try:
            if gpt_model_path:
                response = requests.get(self.tts_server_url + "set_gpt_weights", params={"weights_path": gpt_model_path})
                response.raise_for_status()
                print(f"gpt model switched successfully: {gpt_model_path}")
        except Exception as e:
            print(f"Failed to switch gpt model: {e}")

        try:
            if sovits_model_path:
                response = requests.get(self.tts_server_url + "set_sovits_weights", params={"weights_path": sovits_model_path})
                response.raise_for_status()
                print(f"sovits model switched successfully: {sovits_model_path}")
        except Exception as e:
            print(f"Failed to switch sovits model: {e}")


class IndexTTSAdapter(TTSAdapter):
    """
    Adapter for a hypothetical Index TTS service.
    This demonstrates how a new service can be integrated.
    """
    def __init__(self, index_server_url="http://localhost:8000/"):
        self.index_server_url = index_server_url
        self.current_model = None

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

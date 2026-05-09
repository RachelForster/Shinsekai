"""
Importable mock adapters for use in test files that need to create additional
mock instances beyond what fixtures provide.

conftest.py re-exports these so fixtures still work transparently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from sdk.adapters.llm import LLMAdapter
from sdk.adapters.tts import TTSAdapter
from sdk.adapters.t2i import T2IAdapter
from sdk.adapters.asr import ASRAdapter


class MockLLMAdapter(LLMAdapter):
    """Returns canned responses; records every chat() call for assertions."""

    def __init__(self, responses=None, **kwargs):
        super().__init__(**kwargs)
        self.responses = list(responses) if responses else ["Hello, I am a mock LLM."]
        self.call_history: List[dict] = []
        self._cursor = 0

    def chat(self, messages, stream=False, **kwargs):
        self.call_history.append({"messages": messages, "stream": stream, "kwargs": kwargs})
        if self._cursor >= len(self.responses):
            self._cursor = 0
        resp = self.responses[self._cursor]
        self._cursor += 1

        if stream:
            def _gen():
                for char in resp:
                    chunk = MagicMock()
                    chunk.choices = [MagicMock()]
                    chunk.choices[0].delta = MagicMock()
                    chunk.choices[0].delta.content = char
                    chunk.choices[0].delta.reasoning_content = None
                    chunk.choices[0].delta.tool_calls = None
                    yield chunk
            return _gen()
        else:
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message = MagicMock()
            response.choices[0].message.content = resp
            response.choices[0].message.tool_calls = None
            response.choices[0].message.reasoning_content = None
            return response

    def reset(self):
        self.call_history.clear()
        self._cursor = 0


class MockTTSAdapter(TTSAdapter):
    """Fake TTS: writes a placeholder file and records calls."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.call_history: List[dict] = []
        self._fail_on_next = False

    def generate_speech(self, text, file_path=None, **kwargs):
        self.call_history.append({"text": text, "file_path": file_path, "kwargs": kwargs})
        if self._fail_on_next:
            self._fail_on_next = False
            raise RuntimeError("Mock TTS failure (requested)")
        p = Path(file_path) if file_path else None
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake audio data")
        return str(p) if p else ""

    def switch_model(self, model_info):
        self.call_history.append({"action": "switch_model", "model_info": model_info})

    @classmethod
    def get_config_schema(cls) -> dict:
        return {}


class MockT2IAdapter(T2IAdapter):
    """Fake T2I: writes a placeholder image and records calls."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.call_history: List[dict] = []

    def generate_image(self, prompt: str, file_path: Optional[str] = None, **kwargs) -> Optional[str]:
        self.call_history.append({"prompt": prompt, "file_path": file_path, "kwargs": kwargs})
        p = Path(file_path) if file_path else None
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fake png data")
        return str(p) if p else None

    def switch_model(self, model_info: Dict[str, Any]) -> None:
        self.call_history.append({"action": "switch_model", "model_info": model_info})

    @classmethod
    def get_config_schema(cls) -> dict:
        return {}


class MockASRAdapter(ASRAdapter):
    """Fake ASR: controllable status; records calls."""

    def __init__(self, language: str = "zh", callback=None):
        super().__init__(language, callback or (lambda text, is_final: None))
        self.call_history: List[dict] = []
        self._status = "idle"

    def start(self):
        self.call_history.append("start")
        self._status = "listening"

    def stop(self):
        self.call_history.append("stop")
        self._status = "stopped"

    def get_status(self) -> str:
        return self._status

    def pause(self):
        self.call_history.append("pause")
        self._status = "paused"

    def resume(self):
        self.call_history.append("resume")
        self._status = "listening"

    def simulate_transcription(self, text: str, is_final: bool = True):
        self.callback(text, is_final)

from __future__ import annotations

from abc import ABC, abstractmethod


class TTSAdapter(ABC):
    """Abstract text-to-speech adapter.

    Base defaults and conventions:
        - ``get_config_schema()``: Returns ``{}`` by default (no extra API-tab fields). Non-empty schema
          uses the same meta keys as ``LLMAdapter.get_config_schema``.
        - Constructor arguments are defined by ``TTSAdapterFactory`` and each subclass (e.g.
          ``tts_server_url``, ``gpt_sovits_work_path``); this base does not declare them.
    """

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        """Metadata for adapter-specific options; empty ``{}`` means none."""
        return {}

    def wait_until_ready(self, timeout_seconds: float | None = None) -> None:
        """Wait until the adapter can accept requests.

        In-process and remote adapters are ready after construction by default.
        Adapters that start a local service should override this method and
        raise when the service cannot become ready within the timeout.
        """

        return None

    @abstractmethod
    def generate_speech(self, text, file_path=None, **kwargs):
        pass

    @abstractmethod
    def switch_model(self, model_info):
        pass

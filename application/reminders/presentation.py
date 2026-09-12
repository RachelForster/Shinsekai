"""Character reminder text and speech, independent of an active chat session."""

from collections.abc import Mapping
import json
import logging
from pathlib import Path
import threading
import time
import uuid

from ai.llm.template.reminder import (
    ReminderContext,
    build_reminder_system_section,
    build_reminder_user_section,
)
from ai.tts.model_session import tts_model_session

logger = logging.getLogger(__name__)


def _text_response(response):
    if isinstance(response, (str, Mapping)):
        return response
    choices = getattr(response, "choices", None)
    if choices:
        return choices[0].message.content
    content = getattr(response, "content", None)
    if isinstance(content, list):
        return "".join(
            getattr(block, "text", "")
            for block in content
            if getattr(block, "type", "") == "text"
        )
    return content or getattr(response, "text", "")


class ReminderPresenter:
    def __init__(self, config, project_root):
        self.config = config
        self.audio_dir = Path(project_root).resolve() / "cache" / "reminder_audio"
        self._slots = threading.BoundedSemaphore(1)
        self._tts_adapter = None
        self._tts_signature = None
        self._tts_adapters = []

    def close(self):
        for adapter in self._tts_adapters:
            try:
                # Built-in adapters only terminate subprocesses they started.
                stop = getattr(adapter, "stop_server", None)
                if callable(stop):
                    stop()
            except Exception:
                logger.warning("Reminder TTS cleanup failed", exc_info=True)

    @staticmethod
    def validate(payload):
        if not isinstance(payload, dict):
            raise ValueError("Reminder presentation must be an object")
        result = {}
        for field, maximum in {
            "character_name": 120,
            "title": 120,
            "message": 2000,
            "due_at": 120,
        }.items():
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError(f"Invalid reminder {field}")
            result[field] = value
        return result

    def render(self, payload):
        data = self.validate(payload)
        system = self.config.config.system_config
        display_language = str(getattr(system, "ui_language", "zh_CN"))
        voice_language = str(getattr(system, "voice_language", "ja"))
        fallback = {
            "message": data["message"],
            "speech": data["message"],
            "speech_language": (
                "zh" if display_language == "zh_CN" else display_language
            ),
        }
        character = self.config.get_character_by_name(data["character_name"])
        if character is None or not self._slots.acquire(blocking=False):
            return fallback
        try:
            context = ReminderContext(
                {
                    **data,
                    "character_setting": str(
                        getattr(character, "character_setting", "")
                    )[:12000],
                    "character_brief": str(getattr(character, "character_brief", ""))[
                        :1000
                    ],
                    "display_language": display_language,
                    "voice_language": voice_language,
                }
            )
            raw = self._complete(
                [
                    {
                        "role": "system",
                        "content": build_reminder_system_section().render(context),
                    },
                    {
                        "role": "user",
                        "content": build_reminder_user_section().render(context),
                    },
                ]
            )
            parsed = raw if isinstance(raw, Mapping) else json.loads(str(raw).strip())
            for key in ("message", "speech"):
                if (
                    not isinstance(parsed.get(key), str)
                    or not parsed[key].strip()
                    or len(parsed[key]) > 400
                ):
                    raise ValueError("Invalid generated reminder dialogue")
            return {
                "message": parsed["message"].strip(),
                "speech": parsed["speech"].strip(),
                "speech_language": voice_language,
            }
        except Exception:
            logger.warning(
                "Reminder dialogue generation failed; using saved text", exc_info=True
            )
            return fallback
        finally:
            self._slots.release()

    def _complete(self, messages):
        from ai.llm.llm_manager import LLMAdapterFactory

        provider, model, base_url, api_key = self.config.get_llm_api_config()
        if not provider or not model or (not api_key and provider != "Ollama"):
            raise ValueError("Reminder LLM is not configured")
        adapter = LLMAdapterFactory.create_adapter(
            **self.config.merged_llm_factory_kwargs(
                provider,
                {
                    "llm_provider": provider,
                    "model": model,
                    "base_url": base_url,
                    "api_key": api_key or "ollama",
                },
            )
        )
        client = getattr(adapter, "client", None)
        if callable(getattr(client, "with_options", None)):
            adapter.client = client.with_options(timeout=25, max_retries=0)
        try:
            return _text_response(
                adapter.chat(
                    messages, stream=False, response_format={"type": "json_object"}
                )
            )
        finally:
            close = getattr(getattr(adapter, "client", None), "close", None)
            if callable(close):
                close()

    def speech(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Reminder speech must be an object")
        name, text, language = (
            payload.get(key) for key in ("character_name", "speech", "speech_language")
        )
        if (
            not isinstance(name, str)
            or len(name) > 120
            or not isinstance(text, str)
            or not 0 < len(text) <= 2000
        ):
            raise ValueError("Invalid reminder speech")
        if language not in {"zh_CN", "zh", "en", "ja", "ko", "yue", "auto"}:
            raise ValueError("Invalid reminder speech language")
        character = self.config.get_character_by_name(name)
        if character is None or not self._slots.acquire(blocking=False):
            return {"audio_path": None}
        try:
            return self._synthesize(
                character, text, "zh" if language == "zh_CN" else language
            )
        except Exception:
            logger.warning(
                "Reminder voice unavailable; keeping text reminder", exc_info=True
            )
            return {"audio_path": None}
        finally:
            self._slots.release()

    def _synthesize(self, character, text, language):
        from ai.tts.tts_manager import TTSAdapterFactory

        url, work_path, provider = self.config.get_gpt_sovits_config()
        if not provider or provider == "none":
            return {"audio_path": None}
        kwargs = self.config.merged_tts_factory_kwargs(
            provider,
            {
                "gpt_sovits_work_path": work_path,
                "tts_server_url": url,
            },
        )
        signature = (provider, repr(sorted(kwargs.items())))
        if signature != self._tts_signature:
            self._tts_adapter = TTSAdapterFactory.create_adapter(
                adapter_name=provider, **kwargs
            )
            self._tts_adapters.append(self._tts_adapter)
            self._tts_signature = signature
        adapter = self._tts_adapter
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        path = self.audio_dir / f"{uuid.uuid4().hex}.wav"
        try:
            adapter.wait_until_ready(timeout_seconds=30)
            with tts_model_session(adapter, str(url), timeout=15):
                adapter.switch_model(
                    {
                        "character_name": character.name,
                        "gpt_model_path": self._voice_path(character.gpt_model_path),
                        "sovits_model_path": self._voice_path(
                            character.sovits_model_path
                        ),
                    }
                )
                result = adapter.generate_speech(
                    text=text,
                    file_path=str(path),
                    ref_audio_path=self._voice_path(character.refer_audio_path),
                    prompt_text=character.prompt_text or "",
                    prompt_lang=character.prompt_lang or language,
                    text_lang=language,
                    character_name=character.name,
                    speed_factor=character.speech_speed,
                )
            if not result or not path.is_file() or path.stat().st_size == 0:
                path.unlink(missing_ok=True)
                return {"audio_path": None}
        except Exception:
            path.unlink(missing_ok=True)
            raise
        for old in self.audio_dir.glob("*.wav"):
            if old.stat().st_mtime < time.time() - 7 * 86400:
                old.unlink(missing_ok=True)
        return {
            "audio_path": path.as_posix(),
            "audio_volume": min(1.0, max(0.0, character.speech_volume)),
        }

    def _voice_path(self, value):
        value = str(value or "")
        # Preserve server-side POSIX paths such as /kaggle/... on Windows.
        if not value or Path(value).is_absolute() or value.startswith("/"):
            return value
        return (self.audio_dir.parent.parent / value).resolve().as_posix()

"""Present one standard chat dialog as a desktop reminder, without a chat window."""

import copy
from collections.abc import Callable
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from application.reminders.workflow import ReminderDialogWorkflow
from application.chat.voice_policy import character_speech_disabled
from sdk.messages import LLMDialogMessage

logger = logging.getLogger(__name__)


class ReminderPresenter:
    def __init__(self, config, project_root, *, speech_disabled: Callable[[], bool] | None = None):
        self.config = config
        self.workflow = ReminderDialogWorkflow(config)
        self.project_root = Path(project_root).resolve()
        self.audio_dir = self.project_root / "cache" / "reminder_audio"
        self._slots = threading.BoundedSemaphore(1)
        self._tts_manager = None
        self._tts_signature = None
        self._tts_adapters = []
        self._speech_disabled = speech_disabled or (lambda: character_speech_disabled(self.config))

    def close(self):
        if self._tts_manager is not None:
            # The presenter owns adapter cleanup, including adapters retained
            # across configuration changes. Stop the manager's idle THA queue.
            self._tts_manager.shutdown(stop_server=False)
        for adapter in self._tts_adapters:
            try:
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
        count = payload.get("delivery_count", 0)
        if type(count) is not int or count < 0:
            raise ValueError("Invalid reminder delivery_count")
        result["delivery_count"] = count
        return result

    @staticmethod
    def _presentation(dialog):
        return {"message": dialog.text, "dialog": dialog.model_dump(by_alias=True)}

    def render(self, payload):
        data = self.validate(payload)
        fallback = self._presentation(
            LLMDialogMessage(
                character_name=data["character_name"], speech=data["message"]
            )
        )
        character = self.config.get_character_by_name(data["character_name"])
        if character is None or not self._slots.acquire(blocking=False):
            return fallback
        try:
            return self._presentation(self.workflow.generate(data, character))
        except Exception:
            logger.warning(
                "Reminder dialogue generation failed; using saved text", exc_info=True
            )
            return fallback
        finally:
            self._slots.release()

    def speech(self, payload):
        if self._speech_disabled():
            return {"audio_path": None}
        if not isinstance(payload, dict) or not isinstance(payload.get("dialog"), dict):
            raise ValueError("Reminder speech requires a dialog object")
        dialog = LLMDialogMessage.model_validate(payload["dialog"])
        if (
            not dialog.name.strip()
            or len(dialog.name) > 120
            or not (dialog.text or "").strip()
            or len(dialog.text) > 2000
            or len(dialog.translate or "") > 2000
        ):
            raise ValueError("Invalid reminder dialog")
        character = self.config.get_character_by_name(dialog.name)
        if character is None or not self._slots.acquire(blocking=False):
            return {"audio_path": None}
        try:
            return self._synthesize(character, dialog)
        except Exception:
            logger.warning(
                "Reminder voice unavailable; keeping text reminder", exc_info=True
            )
            return {"audio_path": None}
        finally:
            self._slots.release()

    def _synthesize(self, character, dialog):
        from ai.llm.text_processor import TextProcessor
        from ai.tts.tts_manager import TTSAdapterFactory, TTSManager
        from application.chat.dialog_media.models import TtsGenerationRequest
        from application.chat.dialog_media.resolver import ResolvedSpriteAsset
        from application.chat.dialog_media.tts_generation import (
            DefaultTtsGenerationStrategy,
        )

        url, work_path, provider = self.config.get_gpt_sovits_config()
        if not provider or provider == "none":
            return {"audio_path": None}
        kwargs = self.config.merged_tts_factory_kwargs(
            provider, {"gpt_sovits_work_path": work_path, "tts_server_url": url}
        )
        signature = (provider, repr(sorted(kwargs.items())))
        if self._tts_manager is None:
            self._tts_manager = TTSManager(
                audio_cache_dir=self.audio_dir, unique_cache_files=True
            )
        manager = self._tts_manager
        if signature != self._tts_signature:
            adapter = TTSAdapterFactory.create_adapter(adapter_name=provider, **kwargs)
            self._tts_adapters.append(adapter)
            manager.set_tts_adapter(adapter)
            self._tts_signature = signature
        manager.tts_adapter.wait_until_ready(timeout_seconds=30)
        manager.set_language(self.config.config.system_config.voice_language)
        pronunciation = {}
        for configured in getattr(self.config.config, "characters", [character]):
            pronunciation.update(getattr(configured, "pronunciation_map", None) or {})
        # One reminder utterance produces one replayable file. Preserve the
        # shared speech/translate selection, cleanup and translation fallback.
        api = copy.copy(self.config.config.api_config)
        api.tts_split_enabled = False
        runtime = SimpleNamespace(
            tts_manager=manager,
            text_processor=TextProcessor(pronunciation_map=pronunciation),
            config=SimpleNamespace(
                config=SimpleNamespace(api_config=api),
                get_gpt_sovits_config=self.config.get_gpt_sovits_config,
            ),
        )
        voice_character = copy.copy(character)
        for field in ("gpt_model_path", "sovits_model_path", "refer_audio_path"):
            setattr(
                voice_character, field, self._voice_path(getattr(character, field, ""))
            )
        request = TtsGenerationRequest(
            runtime=runtime,
            character=voice_character,
            character_name=dialog.name,
            message=dialog,
            sprite=ResolvedSpriteAsset(asset_id=str(dialog.asset_id)),
        )
        try:
            paths = list(DefaultTtsGenerationStrategy().generate(request))
        finally:
            for partial in self.audio_dir.glob("*.wav.part"):
                partial.unlink(missing_ok=True)
        if not paths or not paths[0] or not Path(paths[0]).is_file():
            return {"audio_path": None}
        for old in self.audio_dir.glob("*.wav"):
            if old.stat().st_mtime < time.time() - 7 * 86400:
                old.unlink(missing_ok=True)
        return {
            # /api/media serves project-relative files; absolute paths require
            # external-media approval that reminders do not register.
            "audio_path": (
                Path(paths[0]).resolve().relative_to(self.project_root).as_posix()
            ),
            "audio_volume": min(1.0, max(0.0, character.speech_volume)),
        }

    def _voice_path(self, value):
        value = str(value or "")
        if not value or Path(value).is_absolute() or value.startswith("/"):
            return value
        return (self.project_root / value).resolve().as_posix()

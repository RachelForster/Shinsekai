"""Run the chat generation and parsing stages for a single reminder utterance."""

from datetime import datetime
import random

from ai.llm.template.core import PROMPT_CATALOG
from ai.llm.template.dialog import DialogTemplateContext
from ai.llm.template.integrations.localization import (
    _target_voice_display_name,
    _ui_voice_same_lang,
    resolve_template_locale,
    translate_template,
)
from ai.llm.template.reminder import (
    REMINDER_PROMPT_SPEC,
    ReminderContext,
    build_reminder_system_section,
    build_reminder_user_section,
)
from core.messaging.dialog_output import has_valid_dialog_output
from core.messaging.stream_parser import LlmResponseStreamParser
from sdk.messages import LLMDialogMessage


REMINDER_STYLE_KEYS = (
    "session.reminder_style_direct",
    "session.reminder_style_caring",
    "session.reminder_style_question",
    "session.reminder_style_playful",
    "session.reminder_style_encouragement",
)

# Vary only the phrasing, never the event's timing, facts or character identity.
REMINDER_EXPRESSION_STYLES = (
    "a simple, direct reminder",
    "a warm, caring nudge",
    "a brief, friendly question",
    "a light playful nudge, only if it fits the character",
    "a short word of encouragement",
)


def reminder_expression_styles(locale: str = "zh_CN") -> tuple[str, ...]:
    return tuple(
        PROMPT_CATALOG.translate(key, locale=locale) for key in REMINDER_STYLE_KEYS
    )


class ReminderDialogWorkflow:
    def __init__(self, config):
        self.config = config

    def generate(self, data, character) -> LLMDialogMessage:
        locale = resolve_template_locale(self.config)

        def translate(key, **kwargs):
            return translate_template(key, locale=locale, **kwargs)

        now = datetime.now().astimezone()
        previous_count = data.get("delivery_count", 0)
        context = ReminderContext(
            payload={
                **data,
                "current_date": now.date().isoformat(),
                "current_time": now.isoformat(timespec="seconds"),
                "previous_reminder_count": previous_count,
                "reminder_number": previous_count + 1,
                "expression_style": random.choice(reminder_expression_styles(locale)),
            },
            locale=locale,
            dialog=DialogTemplateContext(
                characters=((character.name, character),),
                translate=translate,
                target_voice_name=_target_voice_display_name(self.config, translate),
                json_reminder=translate("closing_json_reminder"),
                locale=locale,
                use_llm_translation=not _ui_voice_same_lang(self.config),
                use_choice=False,
                use_narration=False,
                use_stat=False,
                max_speech_chars=120,
                max_dialog_items=1,
            ),
        )
        raw = self.complete(
            REMINDER_PROMPT_SPEC.render_system(context),
            REMINDER_PROMPT_SPEC.render_user(context),
        )
        if not has_valid_dialog_output(raw):
            raise ValueError("Invalid reminder dialog output")
        # The normal parser supports aliases and translate. Only one utterance
        # from the requested character may reach the reminder surface.
        for message in LlmResponseStreamParser().feed(raw):
            if message.name == character.name and (message.text or "").strip():
                if len(message.text) > 400 or len(message.translate or "") > 400:
                    raise ValueError("Reminder dialogue is too long")
                return message
        raise ValueError("Reminder response has no dialogue from its character")

    def complete(self, system_prompt, user_input):
        from ai.llm.llm_manager import LLMAdapterFactory, LLMManager

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
            # One generation plus the chat workflow's two format-repair attempts
            # fit within the desktop presentation request timeout.
            adapter.client = client.with_options(timeout=10, max_retries=0)
        try:
            api = self.config.config.api_config
            manager = LLMManager(
                adapter,
                user_template=system_prompt,
                tools_enabled=False,
                locale=resolve_template_locale(self.config),
                generation_config={
                    "temperature": float(getattr(api, "temperature", 0.7)),
                    "max_tokens": 1024,
                },
            )
            return manager.chat(
                user_input,
                stream=False,
                dialog_output_required=True,
                include_local_time=False,
            )
        finally:
            close = getattr(getattr(adapter, "client", None), "close", None)
            if callable(close):
                close()

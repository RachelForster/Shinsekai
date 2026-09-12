"""Run the chat generation and parsing stages for a single reminder utterance."""

from ai.llm.template.dialog import DialogTemplateContext
from ai.llm.template.integrations.localization import (
    _target_voice_display_name,
    _ui_voice_same_lang,
)
from ai.llm.template.reminder import (
    ReminderContext,
    build_reminder_system_section,
    build_reminder_user_section,
)
from core.messaging.dialog_output import has_valid_dialog_output
from core.messaging.stream_parser import LlmResponseStreamParser
from i18n import tr_in_bundle
from sdk.messages import LLMDialogMessage


class ReminderDialogWorkflow:
    def __init__(self, config):
        self.config = config

    def generate(self, data, character) -> LLMDialogMessage:
        language = self.config.config.system_config.ui_language

        def translate(key, **kwargs):
            return tr_in_bundle(f"template_gen.{key}", language, **kwargs)

        context = ReminderContext(
            payload=data,
            dialog=DialogTemplateContext(
                characters=((character.name, character),),
                translate=translate,
                target_voice_name=_target_voice_display_name(self.config, translate),
                json_reminder=translate("closing_json_reminder"),
                use_llm_translation=not _ui_voice_same_lang(self.config),
                use_choice=False,
                use_narration=False,
                use_stat=False,
                max_speech_chars=120,
                max_dialog_items=1,
            ),
        )
        raw = self.complete(
            build_reminder_system_section().render(context),
            build_reminder_user_section().render(context),
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

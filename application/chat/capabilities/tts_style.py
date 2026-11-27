"""Session capability and turn context provider for dynamic TTS expressiveness hints."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from ai.llm.template.integrations.localization import resolve_template_locale
from ai.llm.template.session import (
    ALL_TTS_STYLE_CONTEXT_MARKERS,
    TTS_STYLE_CONTEXT_SPEC,
    TtsStyleContextPromptContext,
    strip_system_messages_with_markers,
)
from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    TurnContextProvider,
)
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext


class TtsStyleTurnContextProvider(BaseTurnContextProvider):
    """Inject active TTS capability guidance into the system prompt before each chat turn."""

    capability_id = "tts_style"

    def __init__(
        self,
        *,
        config: Any,
        tts_adapter_getter: Callable[[], Any | None],
        output_format_id: str = DEFAULT_DIALOG_FORMAT_ID,
    ) -> None:
        self._config = config
        self._tts_adapter_getter = tts_adapter_getter
        self._output_format_id = str(output_format_id or DEFAULT_DIALOG_FORMAT_ID)

    def before_chat(self, context: BeforeChatContext) -> None:
        strip_system_messages_with_markers(
            context.messages, ALL_TTS_STYLE_CONTEXT_MARKERS
        )
        adapter = self._tts_adapter_getter()
        if adapter is None:
            return
        supports_inline = bool(getattr(adapter, "supports_inline_voice_tags", False))
        supports_instruct = bool(getattr(adapter, "supports_voice_instruction", False))
        if not (supports_inline or supports_instruct):
            return

        rendered = TTS_STYLE_CONTEXT_SPEC.render_system(
            TtsStyleContextPromptContext(
                supports_inline_voice_tags=supports_inline,
                supports_voice_instruction=supports_instruct,
                output_format_id=self._output_format_id,
                locale=resolve_template_locale(self._config),
            )
        ).strip()
        if rendered:
            context.messages.append({"role": "system", "content": rendered})


class TtsStyleSessionCapability(BaseSessionCapability):
    """Expose active TTS expressiveness flags to the LLM session cleanly."""

    capability_id = "tts_style"

    def __init__(self) -> None:
        self._tts_manager: Any = None
        self._provider: TtsStyleTurnContextProvider | None = None

    def _active_tts_adapter(self) -> Any | None:
        return getattr(self._tts_manager, "tts_adapter", None)

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        self._tts_manager = getattr(context, "tts_manager", None)
        output_format_id = str(
            getattr(context.args, "output_format", DEFAULT_DIALOG_FORMAT_ID)
            or DEFAULT_DIALOG_FORMAT_ID
        )
        self._provider = TtsStyleTurnContextProvider(
            config=context.config,
            tts_adapter_getter=self._active_tts_adapter,
            output_format_id=output_format_id,
        )

        dispatcher = context.hook_dispatcher
        if dispatcher is None and hasattr(context.llm_manager, "hook_dispatcher"):
            dispatcher = getattr(context.llm_manager, "hook_dispatcher", None)
        if dispatcher is not None and hasattr(dispatcher, "register_before_chat"):
            self._provider.delegates_to_hook_dispatcher = True
            dispatcher.register_before_chat(
                self._provider.before_chat,
                label="tts_style_before_chat",
            )

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None:
        if self._tts_manager is None:
            self._tts_manager = getattr(context.runtime, "tts_manager", None) or getattr(
                context.startup, "tts_manager", None
            )
        if self._provider is None:
            output_format_id = str(
                getattr(context.args, "output_format", DEFAULT_DIALOG_FORMAT_ID)
                or DEFAULT_DIALOG_FORMAT_ID
            )
            self._provider = TtsStyleTurnContextProvider(
                config=context.config,
                tts_adapter_getter=self._active_tts_adapter,
                output_format_id=output_format_id,
            )

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()


__all__ = [
    "TtsStyleSessionCapability",
    "TtsStyleTurnContextProvider",
]

"""Create chat providers and startup dependencies outside the process entry point."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol

from core.chat_history.storage import chat_history_active_path

if TYPE_CHECKING:
    from ai.llm.llm_manager import LLMManager
    from ai.t2i.t2i_manager import T2IManager
    from ai.tts.tts_manager import TTSManager
    from config.persistence.config_manager import ConfigManager
    from sdk.chat_init import ChatInitService
    from sdk.manager import PluginManager


logger = logging.getLogger(__name__)


class TranslateText(Protocol):
    def __call__(self, key: str, **kwargs: object) -> str: ...


StartupPhase = Callable[[str], AbstractContextManager[None]]


@dataclass(frozen=True, slots=True)
class ChatStartupContext:
    """Dependencies created while preparing one chat runtime."""

    config: ConfigManager
    llm_manager: LLMManager
    tts_manager: TTSManager | None
    t2i_manager: T2IManager | None
    plugin_manager: PluginManager | None
    messages: list[Any]


class MissingLlmProviderError(RuntimeError):
    """Raised when chat cannot start because no LLM provider is configured."""


def load_chat_config() -> ConfigManager:
    """Load chat configuration without exposing its concrete constructor to main."""

    from config.persistence.config_manager import ConfigManager

    return ConfigManager()


def chat_history_is_present(history_argument: str) -> bool:
    """Return whether the active history file contains a serialized message list."""

    if not str(history_argument or "").strip():
        return False
    active_path = chat_history_active_path(history_argument)
    try:
        return isinstance(json.loads(active_path.read_text(encoding="utf-8")), list)
    except (OSError, json.JSONDecodeError):
        return False


def create_chat_startup_context(
    args: Any,
    *,
    config: ConfigManager,
    init_service: ChatInitService,
    translate: TranslateText,
    phase: StartupPhase | None = None,
    output: Callable[[str], None] = print,
    on_plugins_loaded: Callable[[PluginManager | None], None] | None = None,
) -> ChatStartupContext:
    """Create providers, managers, restored messages, and startup hooks."""

    startup_phase = phase or (lambda _step: nullcontext())

    with startup_phase("plugins.import"):
        runtime = _import_provider_runtime()
    with startup_phase("plugins.load"):
        plugin_manager = _load_plugin_manager(config, runtime)
    if on_plugins_loaded is not None:
        on_plugins_loaded(plugin_manager)

    t2i_manager = _initialize_t2i(
        args,
        config,
        init_service,
        runtime,
        phase=startup_phase,
    )
    tts_manager, tts_provider = _initialize_tts(
        args,
        config,
        init_service,
        runtime,
        phase=startup_phase,
    )

    output(translate("main.print_load_template", a=args))
    with startup_phase("template.load"):
        messages, user_template = _load_chat_inputs(
            args, translate=translate, output=output
        )

    llm_provider, llm_model, base_url, api_key = config.get_llm_api_config()
    logger.info(
        "LLM configuration selected",
        extra={
            "event": "llm.config.selected",
            "provider": llm_provider,
            "model": llm_model,
            "custom_base_url": bool(base_url),
            "auth_configured": bool(api_key),
        },
    )
    if not llm_provider:
        raise MissingLlmProviderError("No language model provider is configured.")

    character_names = _memory_character_names(args, config)
    with startup_phase("llm.init"):
        llm_adapter = runtime.LLMAdapterFactory.create_adapter(
            **config.merged_llm_factory_kwargs(
                llm_provider,
                {
                    "llm_provider": llm_provider,
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": llm_model,
                },
            )
        )
        llm_manager = runtime.LLMManager(
            adapter=llm_adapter,
            user_template=user_template,
            max_tokens=int(config.config.api_config.max_context_tokens),
            compact_threshold=float(config.config.api_config.compact_threshold),
            compact_target_ratio=float(config.config.api_config.compact_target_ratio),
            history_recent_messages=int(
                config.config.api_config.history_recent_messages
            ),
            max_tool_result_chars=int(config.config.api_config.max_tool_result_chars),
            max_active_tool_groups=int(config.config.api_config.max_active_tool_groups),
            generation_config={
                "temperature": float(config.config.api_config.temperature),
                "repetition_penalty": float(
                    config.config.api_config.repetition_penalty
                ),
                "presence_penalty": float(config.config.api_config.presence_penalty),
                "frequency_penalty": float(config.config.api_config.frequency_penalty),
                "max_tokens": 4096,
            },
            history_file=(
                str(chat_history_active_path(args.history)) if args.history else ""
            ),
            hook_dispatcher=(
                plugin_manager.hook_dispatcher if plugin_manager is not None else None
            ),
        )
        if plugin_manager is not None:
            runtime.install_memory_hooks(
                plugin_manager.hook_dispatcher,
                llm_adapter=llm_adapter,
                character_names=character_names,
            )

    with startup_phase("chat.init_hooks"):
        if plugin_manager is not None:
            init_context = runtime.InitChatContext(
                service=init_service,
                character_names=tuple(character_names),
                tts_provider=tts_provider,
                voice_language=str(config.config.system_config.voice_language or "ja"),
                memory_enabled=_memory_auto_enabled(),
                runtime_mode=(
                    "react"
                    if args.stream_endpoint
                    else "headless" if args.headless else "native"
                ),
                headless=bool(args.headless),
                metadata={"workflowPath": str(args.workflow or "")},
            ).scaled(0.68, 0.82)
            plugin_manager.hook_dispatcher.dispatch_init_chat(init_context)

    if messages:
        llm_manager.set_messages(messages)

    return ChatStartupContext(
        config=config,
        llm_manager=llm_manager,
        tts_manager=tts_manager,
        t2i_manager=t2i_manager,
        plugin_manager=plugin_manager,
        messages=messages,
    )


def _import_provider_runtime() -> SimpleNamespace:
    from ai.asr.asr_manager import ASRAdapterFactory
    from ai.llm.llm_manager import LLMAdapterFactory, LLMManager
    from ai.memory.hooks import install_memory_hooks
    from ai.t2i.t2i_manager import T2IAdapterFactory, T2IManager
    from ai.tools.tool_manager import ToolManager
    from ai.tts.tts_manager import TTSAdapterFactory, TTSManager
    from ai.vision.fallback_registry import configure_registered_fallbacks
    from plugin_system.host import ensure_plugins_loaded, PluginRuntimeBindings
    from sdk.chat_init import InitChatContext

    return SimpleNamespace(
        ASRAdapterFactory=ASRAdapterFactory,
        InitChatContext=InitChatContext,
        LLMAdapterFactory=LLMAdapterFactory,
        LLMManager=LLMManager,
        PluginRuntimeBindings=PluginRuntimeBindings,
        T2IAdapterFactory=T2IAdapterFactory,
        T2IManager=T2IManager,
        TTSAdapterFactory=TTSAdapterFactory,
        TTSManager=TTSManager,
        ToolManager=ToolManager,
        configure_registered_fallbacks=configure_registered_fallbacks,
        ensure_plugins_loaded=ensure_plugins_loaded,
        install_memory_hooks=install_memory_hooks,
    )


def _load_plugin_manager(
    config: ConfigManager, runtime: SimpleNamespace
) -> PluginManager | None:
    def register_mcp_tools(tool_manager: Any) -> None:
        from ai.tools.mcp_tool_setup import register_mcp_tools_from_config

        register_mcp_tools_from_config(tool_manager)

    return runtime.ensure_plugins_loaded(
        config,
        runtime_bindings=runtime.PluginRuntimeBindings(
            llm_adapters=runtime.LLMAdapterFactory._adapters,
            tts_adapters=runtime.TTSAdapterFactory._adapters,
            asr_adapters=runtime.ASRAdapterFactory._adapters,
            t2i_adapters=runtime.T2IAdapterFactory._adapters,
            create_tool_manager=runtime.ToolManager,
            configure_vision_fallbacks=runtime.configure_registered_fallbacks,
            register_mcp_tools=register_mcp_tools,
        ),
    )


def _initialize_t2i(
    args: Any,
    config: ConfigManager,
    init_service: ChatInitService,
    runtime: SimpleNamespace,
    *,
    phase: StartupPhase,
) -> T2IManager | None:
    if not args.t2i:
        return None
    with phase("t2i.init"):
        raw = str(args.t2i or "").strip()
        adapter_name = (
            str(config.config.api_config.t2i_provider or "comfyui").strip()
            if raw.lower() == "comfyui"
            else raw
        )
        try:
            adapter = runtime.T2IAdapterFactory.create_adapter(
                adapter_name=adapter_name,
                **config.merged_t2i_factory_kwargs(
                    adapter_name,
                    {
                        "work_path": config.config.api_config.t2i_work_path,
                        "api_url": config.config.api_config.t2i_api_url,
                        "workflow_path": config.config.api_config.t2i_default_workflow_path,
                        "prompt_node_id": config.config.api_config.t2i_prompt_node_id,
                        "output_node_id": config.config.api_config.t2i_output_node_id,
                    },
                ),
            )
            return runtime.T2IManager(adapter)
        except Exception:
            init_service.report(
                phase="t2i.init",
                message="Image generation is unavailable; continuing without it.",
                log="Image generation initialization failed and was skipped.",
            )
            logger.exception(
                "T2I initialization failed",
                extra={"event": "t2i.init.failed"},
            )
            return None


def _initialize_tts(
    args: Any,
    config: ConfigManager,
    init_service: ChatInitService,
    runtime: SimpleNamespace,
    *,
    phase: StartupPhase,
) -> tuple[TTSManager | None, str]:
    gsv_url, gsv_api_path, config_provider = config.get_gpt_sovits_config()
    adapter_name = str(args.tts or "").strip() or str(config_provider or "")
    if not adapter_name or adapter_name.casefold() == "none":
        return None, adapter_name
    with phase("tts.init"):
        try:
            adapter = runtime.TTSAdapterFactory.create_adapter(
                adapter_name=adapter_name,
                wait_until_ready=True,
                **config.merged_tts_factory_kwargs(
                    adapter_name,
                    {
                        "gpt_sovits_work_path": gsv_api_path,
                        "tts_server_url": gsv_url,
                    },
                ),
            )
            manager = runtime.TTSManager(tts_server_url=gsv_url)
            manager.set_tts_adapter(adapter=adapter)
            voice_language = (
                str(config.config.system_config.voice_language or "ja").strip() or "ja"
            )
            manager.set_language(voice_language)
            return manager, adapter_name
        except Exception:
            init_service.report(
                phase="tts.init",
                message="Voice service is unavailable; continuing with text chat.",
                log="Voice service initialization failed and was skipped.",
            )
            logger.exception(
                "TTS initialization failed",
                extra={"event": "tts.init.failed"},
            )
            return None, adapter_name


def _load_chat_inputs(
    args: Any,
    *,
    translate: TranslateText,
    output: Callable[[str], None],
) -> tuple[list[Any], str]:
    from application.chat.history_state import load_chat_history

    messages: list[Any] = []
    if args.history:
        output(translate("main.print_load_history", path=args.history))
        messages = load_chat_history(str(chat_history_active_path(args.history)))

    template_path = Path("data/character_templates") / f"{args.template}.txt"
    return messages, template_path.read_text(encoding="utf-8")


def _parse_character_names(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [part.strip() for part in text.split(",")]
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _memory_character_names(args: Any, config: ConfigManager) -> list[str]:
    from application.chat.initial_sprite import find_character_sprite_by_path

    names = _parse_character_names(getattr(args, "characters", ""))
    if names:
        return names
    init_sprite_path = str(getattr(args, "init_sprite_path", "") or "")
    if not init_sprite_path:
        return []
    try:
        matched = find_character_sprite_by_path(config, init_sprite_path)
    except OSError:
        logger.warning(
            "Failed to resolve memory character from initial sprite path",
            extra={
                "event": "memory.character.resolve_failed",
                "sprite_path": init_sprite_path,
            },
            exc_info=True,
        )
        return []
    return [matched[0]] if matched is not None else []


def _memory_auto_enabled() -> bool:
    return str(
        os.environ.get("SHINSEKAI_MEMORY_AUTO_ENABLED") or "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }

"""Session capability and turn context provider for screen/game perception."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    SessionRuntimeCapabilityContext,
    StreamingWiringCapabilityContext,
    TurnAdmissionDecision,
    TurnAdmissionRequest,
    TurnContextProvider,
)

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext, MessageAddedContext


PERCEPTION_CONFIG_KEYS: tuple[str, ...] = (
    "perception_enabled",
    "perception_base_url",
    "perception_api_key",
    "perception_model",
    "perception_use_gguf",
    "perception_interval_sec",
    "perception_capture_interval_sec",
    "perception_ocr_interval_sec",
    "perception_frame_max_side",
    "perception_diff_threshold",
    "perception_ocr_enabled",
    "perception_reflex_enabled",
    "perception_reflex_cooldown_sec",
    "perception_proactive_enabled",
    "perception_salience_threshold",
    "perception_proactive_cooldown_sec",
)


class PerceptionTurnContextProvider(BaseTurnContextProvider):
    """Gate proactive perception turns and expose perception hooks to the turn pipeline."""

    capability_id = "perception"
    delegates_to_hook_dispatcher = True

    def __init__(
        self,
        *,
        hooks: Any,
        coordinator: Any,
        pause_asr: Callable[[], None] | None = None,
    ) -> None:
        self.hooks = hooks
        self.coordinator = coordinator
        self._pause_asr = pause_asr

    def set_pause_asr(self, pause_asr: Callable[[], None] | None) -> None:
        self._pause_asr = pause_asr

    def admit_turn(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnAdmissionDecision | None:
        source = str(request.source or "user").strip() or "user"
        if not self.hooks.prepare_turn(request.history_turn_id, source):
            return TurnAdmissionDecision(
                admitted=False,
                record_user_message=False,
            )
        if source == "perception":
            self.coordinator.mark_proactive_turn_admitted()
            if callable(self._pause_asr):
                self._pause_asr()
            return TurnAdmissionDecision(
                admitted=True,
                record_user_message=False,
            )
        return TurnAdmissionDecision(
            admitted=True,
            record_user_message=(source == "user"),
        )

    def before_chat(self, context: BeforeChatContext) -> None:
        self.hooks.before_chat(context)

    def message_added(self, context: MessageAddedContext) -> None:
        self.hooks.message_added(context)


class PerceptionSessionCapability(BaseSessionCapability):
    """Own `PerceptionCoordinator`, hooks, ASR pause binding, and realtime commands."""

    capability_id = "perception"

    def __init__(self) -> None:
        self.coordinator: Any | None = None
        self._provider: PerceptionTurnContextProvider | None = None
        self._context: SessionRuntimeCapabilityContext | None = None
        self._plugin_runtime_bound = False

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None:
        if context.mode != "stream":
            return
        from ai.perception.cloud_summary import create_cloud_text_completer
        from application.perception import (
            PerceptionCoordinator,
            create_default_cursor_probe,
            install_perception_hooks,
        )
        from plugin_system.host import bind_perception_runtime
        from sdk.hooks import PluginHookDispatcher

        self._context = context
        self.coordinator = PerceptionCoordinator(
            get_api_config=lambda: getattr(
                getattr(context.config, "config", None), "api_config", None
            ),
            resolve_character=self._resolve_perception_character,
            is_chat_busy=self._is_chat_busy_for_perception,
            apply_reflex=self._apply_perception_reflex,
            enqueue_proactive_turn=self._enqueue_proactive_perception_turn,
            publish_state=lambda state: context.transport.emit(
                {"type": "perception.state", "perception": state}
            ),
            notify_once=getattr(context.ui_updates, "post_notification", None),
            cloud_complete=create_cloud_text_completer(context.config),
            cursor_probe=create_default_cursor_probe(),
        )
        dispatcher = getattr(context.startup.llm_manager, "hook_dispatcher", None)
        if dispatcher is None:
            dispatcher = PluginHookDispatcher()
            context.startup.llm_manager.hook_dispatcher = dispatcher
        hooks = install_perception_hooks(
            dispatcher,
            rp_input_cache=self.coordinator.rp_input_cache,
            gatekeeper=self.coordinator.gatekeeper,
            is_enabled=self.coordinator.is_effectively_enabled,
            proactive_threshold=self.coordinator.proactive_turn_threshold,
        )
        self._provider = PerceptionTurnContextProvider(
            hooks=hooks,
            coordinator=self.coordinator,
        )
        bind_perception_runtime(self.coordinator.ingest)
        self._plugin_runtime_bound = True

    def bind_streaming_session(
        self,
        context: StreamingWiringCapabilityContext,
    ) -> None:
        if self._provider is None:
            return
        runtime_asr = getattr(context.bindings, "runtime_asr", None)
        pause_fn = getattr(runtime_asr, "pause_for_turn", None)
        self._provider.set_pause_asr(pause_fn if callable(pause_fn) else None)

    def on_session_ready(self) -> None:
        if self.coordinator is not None:
            self.coordinator.start()

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()

    def command_handlers(self) -> Mapping[str, Callable[[object], None]]:
        if self._context is None:
            return {}
        return {
            "perception-ingest": self._handle_ingest,
            "perception-clear": self._handle_clear,
            "perception-config-sync": self._handle_config_sync,
        }

    def pre_shutdown_action(self) -> Callable[[], None] | None:
        if self.coordinator is None:
            return None
        return self.coordinator.stop

    def on_shutdown(self) -> None:
        if self._plugin_runtime_bound:
            from plugin_system.host import bind_perception_runtime

            bind_perception_runtime(None)
            self._plugin_runtime_bound = False

    def _handle_ingest(self, payload: object) -> None:
        if self.coordinator is None:
            return
        if not isinstance(payload, Mapping):
            raise ValueError("Perception ingest payload must be an object.")
        self.coordinator.ingest(payload)

    def _handle_clear(self, _payload: object) -> None:
        if self.coordinator is None:
            return
        self.coordinator.clear()

    def _handle_config_sync(self, payload: object) -> None:
        if self._context is None or not isinstance(payload, Mapping):
            return
        config = self._context.config
        api_config = config.config.api_config.model_copy(deep=True)
        for key in PERCEPTION_CONFIG_KEYS:
            if key in payload:
                setattr(api_config, key, payload[key])
        config.config.api_config = api_config
        if self.coordinator is not None:
            self.coordinator._emit_state()

    def _resolve_perception_character(self) -> Any | None:
        ctx = self._context
        if ctx is None:
            return None
        player_name = str(getattr(ctx.args, "player_character", "") or "").strip()
        sink = getattr(ctx.transport, "stream_sink", None)
        snapshot = (
            sink.snapshot()
            if sink is not None and hasattr(sink, "snapshot")
            else {}
        )
        if isinstance(snapshot, dict):
            sprites = snapshot.get("sprites")
            if isinstance(sprites, list):
                for item in reversed(sprites):
                    if not isinstance(item, dict):
                        continue
                    candidate = str(
                        item.get("characterName") or item.get("label") or ""
                    ).strip()
                    if candidate and candidate != player_name:
                        char = ctx.config.get_character_by_name(candidate)
                        if char is not None:
                            return char
        for candidate in getattr(ctx.startup, "character_names", ()) or ():
            name = str(candidate or "").strip()
            if name and name != player_name:
                char = ctx.config.get_character_by_name(name)
                if char is not None:
                    return char
        for char in getattr(ctx.config.config, "characters", ()) or ():
            name = str(getattr(char, "name", "") or "").strip()
            if name and name != player_name:
                return char
        return None

    def _is_chat_busy_for_perception(self) -> bool:
        ctx = self._context
        if ctx is None:
            return False
        runtime = ctx.runtime
        if (
            runtime is not None
            and runtime.input_queue is not None
            and not runtime.input_queue.empty()
        ):
            return True
        if ctx.chat_turn_service is not None:
            if ctx.chat_turn_service.is_active():
                return True
            batch = ctx.chat_turn_service.batch_state()
            if batch.pending_count > 0 or batch.typing:
                return True
        sink = getattr(ctx.transport, "stream_sink", None)
        if sink is not None and hasattr(sink, "snapshot"):
            snapshot = sink.snapshot()
            if isinstance(snapshot, dict):
                if str(snapshot.get("status") or "") in {
                    "generating",
                    "streaming",
                    "speaking",
                    "replaying",
                }:
                    return True
                if snapshot.get("activePlayback"):
                    return True
        return False

    def _apply_perception_reflex(
        self,
        character_name: str,
        sprite_idx: int | None,
        bark: str,
    ) -> None:
        ctx = self._context
        if ctx is None or ctx.ui_updates is None:
            return
        if sprite_idx is not None:
            ctx.ui_updates.update_sprite(character_name, sprite_idx)
        if bark:
            ctx.ui_updates.post_sprite_reaction(character_name, bark)

    def _enqueue_proactive_perception_turn(self, prompt: str) -> bool:
        from sdk.messages import UserInputMessage

        ctx = self._context
        if ctx is None or ctx.runtime is None or ctx.runtime.input_queue is None:
            return False
        if self._is_chat_busy_for_perception():
            return False
        ctx.runtime.input_queue.put(
            UserInputMessage(
                text=prompt,
                attachments=[],
                source="perception",
            )
        )
        return True

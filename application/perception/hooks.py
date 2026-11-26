"""Chat lifecycle hooks integrating `RPInputCache` and `PerceptionGatekeeper`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.llm.template.perception import (
    build_perception_translator,
    render_perception_turn_reply_suffix,
    render_proactive_collapsed_history,
)
from core.chat_history.identity import CHAT_TURN_ID
from core.perception.cache import PERCEPTION_CONTEXT_MARKER, RPInputCache
from core.perception.gatekeeper import PerceptionGatekeeper
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher
from sdk.logging import get_logger


logger = get_logger(__name__)


class PerceptionAutoHooks:
    """Injects cached game perception into `BeforeChatContext` and tracks turn activity."""

    def __init__(
        self,
        *,
        rp_input_cache: RPInputCache,
        gatekeeper: PerceptionGatekeeper,
        is_enabled=lambda: True,
        proactive_threshold: Callable[[], float | None] = lambda: 0.0,
        locale: LocaleInput = None,
    ) -> None:
        self.rp_input_cache = rp_input_cache
        self.gatekeeper = gatekeeper
        self._is_enabled = is_enabled
        self._proactive_threshold = proactive_threshold
        self._locale: LocaleInput = locale
        self._turn_id = ""
        self._turn_context = ""

    def _active_locale(self) -> str:
        return resolve_dynamic_locale(self._locale)

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_before_chat(
            self.before_chat,
            label="perception_auto_before_chat",
        )
        dispatcher.register_message_added(
            self.message_added,
            label="perception_auto_message_added",
        )

    def prepare_turn(self, turn_id: str, source: str) -> bool:
        """Take one snapshot for the dequeued chat event, shared by every request in the turn."""
        proactive = source == "perception"
        self._turn_id = turn_id
        self._turn_context = ""
        active_locale = self._active_locale()
        if self._is_enabled() or (not proactive and self.rp_input_cache.has_context()):
            threshold = self._proactive_threshold() if proactive else 0.0
            if threshold is not None:
                self._turn_context = self.rp_input_cache.take_turn_context(
                    turn_id=turn_id,
                    proactive=proactive,
                    salience_threshold=threshold,
                    allow_consumed_context=not proactive,
                    translate=build_perception_translator(active_locale),
                )
        if proactive and self._turn_context:
            self.gatekeeper.notify_proactive_fired()
        return not proactive or bool(self._turn_context)

    def before_chat(self, context: BeforeChatContext) -> None:
        active_locale = self._active_locale()
        collapsed_marker = render_proactive_collapsed_history(locale=active_locale)
        user = next((msg for msg in reversed(context.messages) if msg.get("role") == "user"), None)
        for message in context.messages:
            if message is not user and message.get("role") == "user" and message.get("source") == "perception":
                message["content"] = collapsed_marker
        if user is None:
            return
        content = user.get("content")
        if PERCEPTION_CONTEXT_MARKER in str(content or ""):
            return
        turn_id = user.get(CHAT_TURN_ID)
        if turn_id:
            block = self._turn_context if turn_id == self._turn_id else ""
        elif (self._is_enabled() or self.rp_input_cache.has_context()) and user.get("source") != "perception":
            block = self.rp_input_cache.take_turn_context(
                allow_consumed_context=True,
                translate=build_perception_translator(active_locale),
            )
        else:
            block = ""
        if not block:
            return
        reply_suffix = render_perception_turn_reply_suffix(locale=active_locale)
        block = f"{block}\n\n{reply_suffix}"
        if isinstance(content, list):
            user["content"] = [*content, {"type": "text", "text": block}]
        else:
            user["content"] = f"{content or ''}\n\n{block}"
        source = user.get("source") or "user"
        logger.info(
            "Perception context attached (source=%s)\n%s",
            source,
            block,
            extra={
                "event": "perception.context.submitted",
                "source": source,
                "history_turn_id": turn_id or "",
            },
        )

    def message_added(self, context: MessageAddedContext) -> None:
        role = str(context.role or "")
        message: dict[str, Any] = context.message or {}
        is_real_user = role == "user" and message.get("source") != "perception"
        if role == "assistant" or is_real_user:
            self.gatekeeper.notify_conversation_activity(from_user=is_real_user)


def install_perception_hooks(
    dispatcher: PluginHookDispatcher,
    *,
    rp_input_cache: RPInputCache,
    gatekeeper: PerceptionGatekeeper | None = None,
    is_enabled=lambda: True,
    proactive_threshold: Callable[[], float | None] = lambda: 0.0,
    locale: LocaleInput = None,
) -> PerceptionAutoHooks:
    """Create and register `PerceptionAutoHooks` on `dispatcher`."""
    hooks = PerceptionAutoHooks(
        rp_input_cache=rp_input_cache,
        gatekeeper=gatekeeper or PerceptionGatekeeper(),
        is_enabled=is_enabled,
        proactive_threshold=proactive_threshold,
        locale=locale,
    )
    hooks.register(dispatcher)
    return hooks

"""Host implementation of :class:`sdk.session_behavior.SessionRuntimePort`."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any
import uuid

from ai.llm.adapter_factory import LLMAdapterFactory
from ai.llm.adapters.common import filter_adapter_chat_params
from sdk.frontend_ui import _controller_for_plugin
from sdk.messages import LLMDialogMessage
from sdk.session_behavior import (
    BehaviorStateEnvelope,
    BehaviorTransition,
    CharacterSummaryView,
)


def _extract_chat_completion_text(adapter: Any, response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if (
        isinstance(response, Iterator) or hasattr(response, "__iter__")
    ) and not isinstance(response, (Mapping, bytes, bytearray, str)):
        parts: list[str] = []
        iter_stream = getattr(adapter, "iter_response_stream", None)
        if callable(iter_stream):
            for delta in iter_stream(response, cancelled=lambda: False):
                piece = getattr(delta, "content", None)
                if piece:
                    parts.append(str(piece))
            return "".join(parts)
        for chunk in response:
            if isinstance(chunk, str):
                parts.append(chunk)
            else:
                parts.append(str(getattr(chunk, "content", "") or ""))
        return "".join(parts)
    decoded = adapter.decode_response(response)
    return str(getattr(decoded, "content", "") or "")


class HostSessionRuntimePort:
    """Thread-safe host port isolating LLM credentials, queues, and UI events from plugins."""

    def __init__(
        self,
        *,
        plugin_id: str,
        config: Any,
        runtime_components: Any = None,
        app_runtime: Any = None,
        capability: Any = None,
    ) -> None:
        self._plugin_id = str(plugin_id or "").strip()
        self._config = config
        self._runtime_components = runtime_components
        self._app_runtime = app_runtime
        self._capability = capability
        self._last_presentation_id: str = ""

    def complete_llm(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        extra_params: Mapping[str, Any] | None = None,
    ) -> str:
        """Execute an isolated stateless LLM completion using host credentials."""
        llm_provider, default_model, base_url, api_key = (
            self._config.get_llm_api_config()
        )
        if not llm_provider:
            raise RuntimeError("No language model provider is configured.")

        resolved_model = str(model or default_model or "")
        adapter = LLMAdapterFactory.create_adapter(
            **self._config.merged_llm_factory_kwargs(
                llm_provider,
                {
                    "llm_provider": llm_provider,
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": resolved_model,
                },
            )
        )
        api_config = getattr(getattr(self._config, "config", None), "api_config", None)
        raw_params: dict[str, Any] = {}
        if extra_params:
            raw_params.update(dict(extra_params))
        if temperature is not None:
            raw_params["temperature"] = float(temperature)
        elif api_config is not None and hasattr(api_config, "temperature"):
            raw_params.setdefault("temperature", float(api_config.temperature))
        if max_tokens is not None:
            raw_params["max_tokens"] = int(max_tokens)

        filtered = filter_adapter_chat_params(adapter, raw_params)
        payload_messages = [dict(message) for message in messages]
        response = adapter.chat(payload_messages, stream=False, **filtered)
        return _extract_chat_completion_text(adapter, response)

    def list_characters(self) -> tuple[CharacterSummaryView, ...]:
        """Return read-only character metadata views without exposing secrets."""
        config_root = getattr(self._config, "config", None)
        characters = getattr(config_root, "characters", None) or ()
        views: list[CharacterSummaryView] = []
        for character in characters:
            name = str(getattr(character, "name", "") or "").strip()
            if not name:
                continue
            display_name = str(getattr(character, "display_name", "") or "").strip()
            aliases = (display_name,) if display_name and display_name != name else ()
            description = str(
                getattr(character, "character_brief", "")
                or getattr(character, "character_setting", "")
                or ""
            ).strip()
            raw_tags = str(getattr(character, "emotion_tags", "") or "").strip()
            tags = tuple(part.strip() for part in raw_tags.split(",") if part.strip())
            sprite_groups = tuple(
                str(group).strip()
                for group in (getattr(character, "sprite_groups", None) or ())
                if str(group).strip()
            )
            has_voice = bool(
                str(getattr(character, "refer_audio_path", "") or "").strip()
                or str(getattr(character, "gpt_model_path", "") or "").strip()
                or str(getattr(character, "sovits_model_path", "") or "").strip()
            )
            views.append(
                CharacterSummaryView(
                    name=name,
                    description=description,
                    aliases=aliases,
                    tags=tags,
                    sprite_groups=sprite_groups,
                    has_voice=has_voice,
                )
            )
        return tuple(views)

    def _resolve_dialog_queue(self) -> Any | None:
        direct = getattr(self._runtime_components, "dialog_queue", None)
        if direct is not None:
            return direct
        workflow = getattr(self._runtime_components, "workflow", None)
        if workflow is not None:
            try:
                from application.runtime.workflow import get_chat_workflow_handles

                handles = get_chat_workflow_handles(workflow)
                if getattr(handles, "dialog_queue", None) is not None:
                    return handles.dialog_queue
            except Exception:
                pass
        if self._app_runtime is not None:
            return getattr(self._app_runtime, "dialog_queue", None)
        return None

    def deliver_dialogs(
        self,
        dialogs: Sequence[LLMDialogMessage | Mapping[str, Any]],
    ) -> int:
        """Enqueue plugin-authored dialog items for sprite, voice, and UI rendering."""
        queue = self._resolve_dialog_queue()
        if queue is None:
            raise RuntimeError("Dialog delivery queue is unavailable.")
        delivered = 0
        for item in dialogs:
            if isinstance(item, LLMDialogMessage):
                msg = item.model_copy(
                    update={"turn_id": None, "dialog_id": uuid.uuid4().hex}
                )
            elif isinstance(item, Mapping):
                parsed = LLMDialogMessage.model_validate(dict(item))
                msg = parsed.model_copy(
                    update={"turn_id": None, "dialog_id": uuid.uuid4().hex}
                )
            else:
                raise TypeError(
                    "deliver_dialogs entries must be LLMDialogMessage or mapping objects"
                )
            queue.put(msg)
            delivered += 1
        return delivered

    def commit_async_transition(
        self,
        *,
        expected_state_version: int,
        transition: BehaviorTransition,
        branch_id: str | None = None,
    ) -> BehaviorStateEnvelope:
        """Commit a transition produced outside synchronous command handling via OCC."""
        if self._capability is None:
            raise RuntimeError("SessionBehaviorCapability is unavailable.")
        return self._capability.commit_external_transition(
            expected_state_version=expected_state_version,
            transition=transition,
            branch_id=branch_id,
        )

    def present_plugin_page(
        self,
        page_id: str,
        *,
        title: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> None:
        """Present a registered overlay page scoped to this behavior's plugin_id."""
        if not self._plugin_id:
            raise RuntimeError("Behavior plugin_id is unavailable.")
        payload: dict[str, Any] = {}
        if title:
            payload["title"] = str(title)
        if params:
            payload["params"] = dict(params)
        controller = _controller_for_plugin(self._plugin_id)
        self._last_presentation_id = controller.present_page(
            page_id,
            mode="overlay",
            payload=payload or None,
        )

    def dismiss_plugin_page(self, page_id: str | None = None) -> None:
        """Dismiss the active overlay page previously presented by this plugin."""
        if not self._plugin_id:
            return
        target = str(page_id or self._last_presentation_id or "").strip()
        if not target:
            return
        controller = _controller_for_plugin(self._plugin_id)
        controller.dismiss_page(target)
        if target == self._last_presentation_id:
            self._last_presentation_id = ""

    def emit_custom_event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Emit a namespaced custom event onto the active frontend stream."""
        clean_type = str(event_type or "").strip()
        if not clean_type:
            raise ValueError("event_type must be non-empty.")
        if self._capability is None:
            return
        self._capability.emit_runtime_event(
            {
                "type": "plugin.behavior.event",
                "pluginId": self._plugin_id,
                "eventType": clean_type,
                "payload": dict(payload),
            }
        )


__all__ = ["HostSessionRuntimePort"]

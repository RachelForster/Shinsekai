"""Session capability and turn context provider for character relationship context."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai.llm.template.dialog.context import DialogTemplateContext
from ai.llm.template.dialog.sections.relation import RelationSection
from ai.llm.template.integrations.localization import translate_template
from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    StartupCapabilityContext,
    TurnContextProvider,
)

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext


logger = logging.getLogger(__name__)

RELATION_CONTEXT_MARKER = "[Shinsekai character relation context]"


def _character_config_mtime_ns(config: Any) -> int | None:
    raw_path = getattr(config, "_CHARACTERS_CONFIG_PATH", None)
    if not raw_path:
        return None
    try:
        return Path(raw_path).stat().st_mtime_ns
    except OSError:
        return None


def _parse_primary_character_names(raw: object) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple, set, frozenset)):
        return tuple(str(item or "").strip() for item in raw if str(item or "").strip())
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parts = tuple(part.strip() for part in text.split(",") if part.strip())
        return parts or None
    if not isinstance(parsed, list):
        return None
    return tuple(str(item or "").strip() for item in parsed if str(item or "").strip())


def _resolve_character_record(config: Any, candidate: str) -> Any | None:
    lookup = getattr(config, "get_character_by_name", None)
    char = lookup(candidate) if callable(lookup) else None
    if char is not None:
        return char
    all_chars = getattr(getattr(config, "config", None), "characters", None)
    if isinstance(all_chars, (list, tuple)):
        key = candidate.casefold()
        return next(
            (
                item
                for item in all_chars
                if str(getattr(item, "name", "") or "").strip().casefold() == key
            ),
            None,
        )
    return None


def _resolve_session_characters(
    config: Any,
    character_names: Sequence[str],
    *,
    player_character: str = "",
    allow_player_dialogue: bool = True,
) -> list[tuple[str, Any]]:
    seen: set[str] = set()
    resolved: list[tuple[str, Any]] = []
    player_name = str(player_character or "").strip()
    excluded_player_keys: set[str] = set()
    if player_name and not allow_player_dialogue:
        excluded_player_keys.add(player_name.casefold())
        player_char = _resolve_character_record(config, player_name)
        if player_char is not None:
            canonical_player = str(
                getattr(player_char, "name", "") or player_name
            ).strip()
            if canonical_player:
                excluded_player_keys.add(canonical_player.casefold())

    candidates = [
        *(str(name or "").strip() for name in character_names),
        player_name if allow_player_dialogue else "",
    ]
    all_chars = getattr(getattr(config, "config", None), "characters", None)
    had_explicit_selection = any(candidates) or bool(excluded_player_keys)

    for candidate in candidates:
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen or key in excluded_player_keys:
            continue
        char = _resolve_character_record(config, candidate)
        if char is not None:
            canonical = str(getattr(char, "name", "") or candidate).strip()
            if canonical.casefold() in excluded_player_keys:
                continue
            seen.add(canonical.casefold())
            seen.add(key)
            resolved.append((canonical, char))

    if not had_explicit_selection and not resolved and isinstance(all_chars, (list, tuple)):
        for char in all_chars:
            name = str(getattr(char, "name", "") or "").strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                resolved.append((name, char))

    return resolved


class RelationTurnContextProvider(BaseTurnContextProvider):
    """Inject live character relationship graphs into `BeforeChatContext` when updated."""

    capability_id = "relation"

    def __init__(
        self,
        *,
        config: Any,
        character_names: Sequence[str] = (),
        primary_character_names: Sequence[str] | frozenset[str] | set[str] | None = None,
        player_character: str = "",
        allow_player_dialogue: bool = True,
        translate: Callable[..., str] = translate_template,
    ) -> None:
        self.config = config
        self.character_names = tuple(
            str(name or "").strip()
            for name in character_names
            if str(name or "").strip()
        )
        self.primary_character_names: tuple[str, ...] | None = (
            None
            if primary_character_names is None
            else tuple(
                str(name or "").strip()
                for name in primary_character_names
                if str(name or "").strip()
            )
        )
        self.player_character = str(player_character or "").strip()
        self.allow_player_dialogue = bool(allow_player_dialogue)
        self.translate = translate
        self._last_mtime_ns = _character_config_mtime_ns(config)

    def _refresh_if_modified(self) -> None:
        refresh = getattr(self.config, "refresh_media_catalogs", None)
        if not callable(refresh):
            return
        current_mtime_ns = _character_config_mtime_ns(self.config)
        if current_mtime_ns is None or current_mtime_ns == self._last_mtime_ns:
            return
        try:
            refresh()
            self._last_mtime_ns = current_mtime_ns
        except Exception:
            logger.debug("Failed to refresh character catalogs for relations", exc_info=True)

    def render_relation_block(self) -> str:
        self._refresh_if_modified()
        characters = _resolve_session_characters(
            self.config,
            self.character_names,
            player_character=self.player_character,
            allow_player_dialogue=self.allow_player_dialogue,
        )
        if not characters:
            return ""
        resolved_primary_names: frozenset[str] | None = None
        if self.primary_character_names is not None:
            primary_keys = {name.casefold() for name in self.primary_character_names}
            resolved_primary_names = frozenset(
                name for name, _char in characters if name.casefold() in primary_keys
            )
        template_context = DialogTemplateContext(
            characters=tuple(characters),
            translate=self.translate,
            target_voice_name="",
            json_reminder="",
            primary_character_names=resolved_primary_names,
        )
        return RelationSection().render(template_context).strip()

    def before_chat(self, context: BeforeChatContext) -> None:
        if any(
            RELATION_CONTEXT_MARKER in str(message.get("content") or "")
            for message in context.messages
        ):
            return
        rendered = self.render_relation_block()
        if not rendered:
            return
        # Avoid duplicate tokens when the active system template already embeds
        # the exact same up-to-date relationship block.
        for message in context.messages:
            if message.get("role") == "system" and rendered in str(
                message.get("content") or ""
            ):
                return
        context.messages.append(
            {
                "role": "system",
                "content": f"{RELATION_CONTEXT_MARKER}\n{rendered}",
            }
        )


class RelationSessionCapability(BaseSessionCapability):
    """Register live character relationship enrichment for active chat sessions."""

    capability_id = "relation"

    def __init__(
        self,
        *,
        translate: Callable[..., str] = translate_template,
    ) -> None:
        self._translate = translate
        self._provider: RelationTurnContextProvider | None = None

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        has_lookup = callable(getattr(context.config, "get_character_by_name", None))
        has_characters = isinstance(
            getattr(getattr(context.config, "config", None), "characters", None),
            (list, tuple),
        )
        if not (has_lookup or has_characters):
            return

        dispatcher = context.hook_dispatcher
        if dispatcher is None and hasattr(context.llm_manager, "hook_dispatcher"):
            dispatcher = getattr(context.llm_manager, "hook_dispatcher", None)
            if dispatcher is None:
                from sdk.hooks import PluginHookDispatcher

                dispatcher = PluginHookDispatcher()
                context.llm_manager.hook_dispatcher = dispatcher

        if dispatcher is None or not hasattr(dispatcher, "register_before_chat"):
            return

        player_character = str(
            getattr(context.args, "player_character", "") or ""
        ).strip()
        allow_player_dialogue = bool(
            getattr(context.args, "allow_player_dialogue", True)
        )
        primary_character_names = (
            context.primary_character_names
            if context.primary_character_names is not None
            else _parse_primary_character_names(
                getattr(context.args, "primary_characters", None)
            )
        )
        self._provider = RelationTurnContextProvider(
            config=context.config,
            character_names=context.character_names,
            primary_character_names=primary_character_names,
            player_character=player_character,
            allow_player_dialogue=allow_player_dialogue,
            translate=self._translate,
        )
        self._provider.delegates_to_hook_dispatcher = True
        dispatcher.register_before_chat(
            self._provider.before_chat,
            label="relation_auto_before_chat",
        )

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()

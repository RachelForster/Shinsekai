"""Session capability and runtime controller for character sprite outfit groups."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import threading
import time
from typing import TYPE_CHECKING, Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    TurnContextProvider,
)
from application.chat.presentation.initial_sprite import find_character_sprite_by_path
from config.character_assets import get_character_assets
from config.sprite_groups import (
    allows_default_group_fallback,
    filter_sprite_indices_for_group,
    has_multiple_sprite_groups,
    list_character_sprite_groups,
    normalize_sprite_group,
    resolve_default_sprite_group,
    resolve_effective_sprite_group,
)
from core.chat_history.models import OutfitState
from core.chat_history.storage import open_session_store, peek_open_session_store
from core.media.asset_tags import tag_contents
from core.sprite.selection import sprite_entry_path

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext, MessageAddedContext


OUTFIT_CONTEXT_MARKER = "[当前角色服装分组状态]"


def _strip_existing_outfit_messages(messages: list[dict[str, Any]]) -> None:
    messages[:] = [
        msg
        for msg in messages
        if not (
            isinstance(msg, Mapping)
            and msg.get("role") == "system"
            and isinstance(msg.get("content"), str)
            and msg["content"].startswith(OUTFIT_CONTEXT_MARKER)
        )
    ]


def _lookup_character(config: Any | None, name: str) -> Any | None:
    cname = str(name or "").strip()
    if not cname or config is None:
        return None
    getter = getattr(config, "get_character_by_name", None)
    if callable(getter):
        return getter(cname)
    for char in getattr(getattr(config, "config", None), "characters", ()) or ():
        if str(getattr(char, "name", "") or "").strip() == cname:
            return char
    return None


class OutfitRuntimeController:
    """Thread-safe per-session active outfit group & lock state controller."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.config: Any | None = None
        self.history_arg: str = ""
        self.media_selection_mode: str = "indexed"
        self.auto_outfit_switch: bool = True
        self.character_names: tuple[str, ...] = ()
        self._states: dict[str, OutfitState] = {}
        self._pending_db_keys: set[str] = set()
        self._transport: Any | None = None
        self._ui_updates: Any | None = None

    def initialize(
        self,
        config: Any,
        *,
        history_arg: str = "",
        media_selection_mode: str = "indexed",
        auto_outfit_switch_arg: bool | None = None,
        initial_outfits_raw: str = "",
        character_names: Sequence[str] = (),
    ) -> None:
        parsed_initial: dict[str, Any] = {}
        raw_text = str(initial_outfits_raw or "").strip()
        if raw_text:
            try:
                loaded = json.loads(raw_text)
                if isinstance(loaded, dict):
                    parsed_initial = loaded
            except (TypeError, ValueError):
                parsed_initial = {}

        open_store = None
        if history_arg:
            open_store = (
                open_session_store(history_arg)
                if auto_outfit_switch_arg is not None or parsed_initial
                else peek_open_session_store(history_arg)
            )
        stored_states = dict(open_store.list_outfit_states()) if open_store is not None else {}
        if auto_outfit_switch_arg is not None:
            auto_switch = auto_outfit_switch_arg
            if open_store is not None:
                open_store.set_auto_outfit_switch(auto_switch)
        else:
            auto_switch = open_store.get_auto_outfit_switch() if open_store is not None else True

        states: dict[str, OutfitState] = {}
        for cname, item in stored_states.items():
            char = _lookup_character(config, cname)
            if char is None or not has_multiple_sprite_groups(char):
                continue
            effective = resolve_effective_sprite_group(char, item.active_group)
            states[cname] = OutfitState(
                character_name=cname,
                active_group=effective,
                locked=bool(item.locked),
                updated_at_ms=int(item.updated_at_ms),
            )

        now_ms = int(time.time() * 1000)
        for raw_cname, spec in parsed_initial.items():
            cname = str(raw_cname or "").strip()
            if not cname or config is None:
                continue
            char = _lookup_character(config, cname)
            if char is None or not has_multiple_sprite_groups(char):
                continue
            if cname in stored_states:
                continue
            req_group = ""
            req_locked = False
            if isinstance(spec, str):
                req_group = spec
            elif isinstance(spec, Mapping):
                req_group = str(
                    spec.get("activeGroup") or spec.get("group") or ""
                ).strip()
                req_locked = bool(spec.get("locked", False))
            matched = self._match_valid_group(char, req_group) or resolve_default_sprite_group(char)
            st = OutfitState(
                character_name=cname,
                active_group=matched,
                locked=req_locked,
                updated_at_ms=now_ms,
            )
            states[cname] = st
            if open_store is not None:
                open_store.set_outfit_state(st)

        candidate_names = list(character_names)
        if config is not None:
            for c in getattr(getattr(config, "config", None), "characters", ()) or ():
                n = str(getattr(c, "name", "") or "").strip()
                if n and n not in candidate_names:
                    candidate_names.append(n)

        for cname in candidate_names:
            if cname in states or config is None:
                continue
            char = _lookup_character(config, cname)
            if char is None or not has_multiple_sprite_groups(char):
                continue
            states[cname] = OutfitState(
                character_name=cname,
                active_group=resolve_default_sprite_group(char),
                locked=False,
                updated_at_ms=0,
            )

        with self._lock:
            self.config = config
            self.history_arg = str(history_arg or "")
            self.media_selection_mode = (
                "semantic"
                if str(media_selection_mode or "").strip().lower() == "semantic"
                else "indexed"
            )
            self.auto_outfit_switch = auto_switch
            self.character_names = tuple(str(n).strip() for n in character_names if str(n).strip())
            self._states = states
            self._pending_db_keys.clear()

    def bind_runtime(self, *, transport: Any | None, ui_updates: Any | None) -> None:
        with self._lock:
            self._transport = transport
            self._ui_updates = ui_updates

    @staticmethod
    def _match_valid_group(character: Any, requested_group: str | None) -> str | None:
        raw = str(requested_group or "").strip()
        if not raw:
            return None
        norm = normalize_sprite_group(raw)
        groups = list_character_sprite_groups(character)
        if norm in groups:
            return norm
        folded = norm.casefold()
        for g in groups:
            if g.casefold() == folded:
                return g
        return None

    def has_any_multi_group_character(self) -> bool:
        with self._lock:
            config = self.config
            names = self.character_names
        if config is None:
            return False
        checked: set[str] = set()
        for cname in names:
            char = _lookup_character(config, cname)
            if char is not None:
                checked.add(cname)
                if has_multiple_sprite_groups(char):
                    return True
        for char in getattr(getattr(config, "config", None), "characters", ()) or ():
            cname = str(getattr(char, "name", "") or "").strip()
            if cname in checked:
                continue
            if has_multiple_sprite_groups(char):
                return True
        return False

    def active_group_for(self, character: Any) -> str | None:
        if character is None or not has_multiple_sprite_groups(character):
            return None
        cname = str(getattr(character, "name", "") or "").strip()
        with self._lock:
            st = self._states.get(cname)
        return resolve_effective_sprite_group(
            character, st.active_group if st is not None else None
        )

    def resolve_initial_sprite_path(self, path: str) -> str:
        if not path or self.config is None:
            return path
        match = find_character_sprite_by_path(self.config, path)
        if match is None:
            return path
        name, index = match
        character = _lookup_character(self.config, name)
        if character is None or not has_multiple_sprite_groups(character):
            return path
        indices = filter_sprite_indices_for_group(character, self.active_group_for(character))
        if not indices:
            return ""
        if index in indices:
            return path
        return sprite_entry_path(get_character_assets(character).sprites[indices[0]])

    def is_locked(self, character_name: str) -> bool:
        cname = str(character_name or "").strip()
        with self._lock:
            st = self._states.get(cname)
            return bool(st.locked) if st is not None else False

    def apply_streamed_outfit_switch(
        self,
        character: Any,
        requested_group: str | None,
    ) -> tuple[bool, str]:
        if character is None or not has_multiple_sprite_groups(character):
            return False, ""
        cname = str(getattr(character, "name", "") or "").strip()
        raw = str(requested_group or "").strip()
        with self._lock:
            prev = self._states.get(cname)
            current = resolve_effective_sprite_group(
                character, prev.active_group if prev is not None else None
            )
            if not raw:
                return False, current
            if (prev is not None and prev.locked) or not self.auto_outfit_switch:
                return False, current
            matched = self._match_valid_group(character, raw)
            if matched is None or matched == current:
                return False, current
            next_state = OutfitState(
                character_name=cname,
                active_group=matched,
                locked=False,
                updated_at_ms=int(time.time() * 1000),
            )
            self._states[cname] = next_state
            if self.history_arg:
                self._pending_db_keys.add(cname)
        self.emit_state()
        return True, matched

    def flush_pending_to_store(self) -> None:
        with self._lock:
            if not self._pending_db_keys:
                return
            to_flush = [
                self._states[k]
                for k in sorted(self._pending_db_keys)
                if k in self._states
            ]
            self._pending_db_keys.clear()
            history_arg = self.history_arg
        if not history_arg or not to_flush:
            return
        open_store = peek_open_session_store(history_arg)
        if open_store is None:
            return
        for st in to_flush:
            open_store.set_outfit_state(st)

    def set_character_outfit(
        self,
        character_name: str,
        *,
        group: str | None = None,
        locked: bool | None = None,
    ) -> OutfitState:
        cname = str(character_name or "").strip()
        if not cname:
            raise ValueError("characterName 不能为空")
        with self._lock:
            config = self.config
        character = _lookup_character(config, cname)
        if character is None:
            raise ValueError(f"未找到角色配置: {cname}")

        with self._lock:
            prev = self._states.get(cname)
            prev_group = resolve_effective_sprite_group(
                character, prev.active_group if prev is not None else None
            )
            prev_locked = bool(prev.locked) if prev is not None else False
            if group is not None and str(group).strip():
                matched = self._match_valid_group(character, group)
                if matched is None:
                    raise ValueError(f"未知的服装分组: {group}")
                next_group = matched
            else:
                next_group = prev_group
            next_locked = bool(locked) if locked is not None else prev_locked
            next_state = OutfitState(
                character_name=cname,
                active_group=next_group,
                locked=next_locked,
                updated_at_ms=int(time.time() * 1000),
            )
            if self.history_arg:
                open_session_store(self.history_arg).set_outfit_state(next_state)
            self._states[cname] = next_state
            self._pending_db_keys.discard(cname)
            group_changed = next_group != prev_group

        self.emit_state()
        if group_changed:
            self._refresh_stage_sprite_if_needed(character, next_group)
        return next_state

    def set_auto_outfit_switch_enabled(self, enabled: bool) -> None:
        with self._lock:
            if self.history_arg:
                open_session_store(self.history_arg).set_auto_outfit_switch(enabled)
            self.auto_outfit_switch = enabled
        self.emit_state()

    def resync_from_session_store(self) -> None:
        with self._lock:
            history_arg = self.history_arg
            config = self.config
            prev_groups = {k: v.active_group for k, v in self._states.items()}
            self._pending_db_keys.clear()
        if config is None:
            return
        open_store = peek_open_session_store(history_arg) if history_arg else None
        stored = dict(open_store.list_outfit_states()) if open_store is not None else {}
        auto_switch = (
            bool(open_store.get_auto_outfit_switch())
            if open_store is not None
            else self.auto_outfit_switch
        )

        next_states: dict[str, OutfitState] = {}
        changed_chars: list[tuple[Any, str]] = []
        all_chars = list(getattr(getattr(config, "config", None), "characters", ()) or ())
        for char in all_chars:
            cname = str(getattr(char, "name", "") or "").strip()
            if not cname or not has_multiple_sprite_groups(char):
                continue
            st = stored.get(cname)
            effective = resolve_effective_sprite_group(
                char, st.active_group if st is not None else None
            )
            next_states[cname] = OutfitState(
                character_name=cname,
                active_group=effective,
                locked=bool(st.locked) if st is not None else False,
                updated_at_ms=int(st.updated_at_ms) if st is not None else 0,
            )
            if prev_groups.get(cname) and prev_groups.get(cname) != effective:
                changed_chars.append((char, effective))

        with self._lock:
            self._states = next_states
            self.auto_outfit_switch = auto_switch
        self.emit_state()
        for char, target_group in changed_chars:
            self._refresh_stage_sprite_if_needed(char, target_group)

    def _refresh_stage_sprite_if_needed(self, character: Any, target_group: str) -> None:
        with self._lock:
            ui_updates = self._ui_updates
            transport = self._transport
        if ui_updates is None or not hasattr(ui_updates, "update_sprite"):
            return
        cname = str(getattr(character, "name", "") or "").strip()
        if not cname:
            return
        indices = filter_sprite_indices_for_group(character, target_group)
        if not indices:
            return
        onstage = False
        sink = getattr(transport, "stream_sink", None) if transport is not None else None
        if sink is not None and hasattr(sink, "snapshot"):
            snap = sink.snapshot()
            if isinstance(snap, dict):
                sprites = snap.get("sprites")
                if isinstance(sprites, list):
                    onstage = any(
                        isinstance(item, dict)
                        and str(item.get("characterName") or item.get("label") or "").strip()
                        == cname
                        for item in sprites
                    )
        if onstage:
            try:
                ui_updates.update_sprite(cname, indices[0])
            except Exception:
                pass

    def build_state_payload(self) -> dict[str, Any]:
        with self._lock:
            config = self.config
            auto_switch = self.auto_outfit_switch
            states_copy = dict(self._states)
            session_names = self.character_names

        outfits: dict[str, dict[str, Any]] = {}
        catalog: dict[str, dict[str, Any]] = {}
        if config is not None:
            target_names = list(session_names) if session_names else [
                str(getattr(c, "name", "") or "").strip()
                for c in (getattr(getattr(config, "config", None), "characters", ()) or ())
            ]
            for cname in target_names:
                if not cname:
                    continue
                char = _lookup_character(config, cname)
                if char is None or not has_multiple_sprite_groups(char):
                    continue
                groups = list_character_sprite_groups(char)
                default_group = resolve_default_sprite_group(char)
                catalog[cname] = {
                    "groups": groups,
                    "defaultGroup": default_group,
                    "fallbackToDefaultGroup": allows_default_group_fallback(char),
                }
                st = states_copy.get(cname)
                effective = resolve_effective_sprite_group(
                    char, st.active_group if st is not None else None
                )
                outfits[cname] = {
                    "characterName": cname,
                    "activeGroup": effective,
                    "locked": bool(st.locked) if st is not None else False,
                    "updatedAtMs": int(st.updated_at_ms) if st is not None else 0,
                }
        return {
            "type": "outfit.state",
            "outfits": outfits,
            "outfitCatalog": catalog,
            "autoOutfitSwitch": auto_switch,
        }

    def emit_state(self) -> None:
        with self._lock:
            transport = self._transport
        if transport is None or not hasattr(transport, "emit"):
            return
        payload = self.build_state_payload()
        if payload["outfitCatalog"] or payload["outfits"]:
            transport.emit(payload)

    def format_before_chat_message(self) -> str:
        with self._lock:
            config = self.config
            session_names = self.character_names
            media_mode = self.media_selection_mode
            auto_switch = self.auto_outfit_switch
            states_copy = dict(self._states)

        if config is None:
            return ""

        target_names = list(session_names) if session_names else [
            str(getattr(c, "name", "") or "").strip()
            for c in (getattr(getattr(config, "config", None), "characters", ()) or ())
        ]
        lines: list[str] = []
        any_unlocked = False
        for cname in target_names:
            if not cname:
                continue
            char = _lookup_character(config, cname)
            if char is None or not has_multiple_sprite_groups(char):
                continue
            groups = list_character_sprite_groups(char)
            st = states_copy.get(cname)
            active_group = resolve_effective_sprite_group(
                char, st.active_group if st is not None else None
            )
            locked = bool(st.locked) if st is not None else False
            if not locked:
                any_unlocked = True
            lock_desc = "已手动锁定（禁止切换服装）" if locked else "未锁定"
            entry = (
                f"- {cname}：当前服装分组「{active_group}」（{lock_desc}；"
                f"可用分组：{' / '.join(groups)}）"
            )
            if media_mode != "semantic":
                assets = get_character_assets(
                    char, getattr(char, "avatar_type", "static")
                )
                tags = tag_contents(assets.emotion_tags, len(assets.sprites))
                indices = filter_sprite_indices_for_group(char, active_group)
                tag_items = [
                    f"{idx + 1}: {tags[idx] or '默认'}"
                    for idx in indices
                    if 0 <= idx < len(assets.sprites)
                ]
                if tag_items:
                    entry += f"\n  当前「{active_group}」分组可用 sprite 编号：{', '.join(tag_items)}"
            lines.append(entry)

        if not lines:
            return ""

        header = [
            OUTFIT_CONTEXT_MARKER,
            "以下角色拥有多套服装立绘分组，请严格遵守组内立绘隔离规则：",
            *lines,
        ]
        if media_mode != "semantic":
            header.append(
                "立绘选择规则：常规对话中，角色的 sprite 字段只能从其【当前服装分组】的可用编号中选择（无需变化填 -1），严禁跨服装分组混用其他服装的编号。"
            )
        if auto_switch and any_unlocked:
            header.append(
                "剧情换装规则：仅当未锁定角色在剧情中明确发生换装事件（如起床/入睡换睡衣、出门换校服/私服、洗漱沐浴、或玩家明确要求换装）时，"
                '可在该角色当句 JSON 中额外附加 `"outfit": "<目标分组名>"` 切换服装；普通情绪、动作或姿态变化严禁输出 `"outfit"` 字段。'
            )
        else:
            header.append(
                '当前已关闭自动换装或服装已锁定：请始终保持当前服装分组，不要输出 `"outfit"` 字段。'
            )
        return "\n".join(header)


class OutfitBeforeChatProvider(BaseTurnContextProvider):
    """Inject active outfit state and valid group sprite IDs before each LLM turn."""

    capability_id = "outfit"

    def __init__(self, controller: OutfitRuntimeController) -> None:
        self.controller = controller

    def before_chat(self, context: BeforeChatContext) -> None:
        _strip_existing_outfit_messages(context.messages)
        content = self.controller.format_before_chat_message()
        if content:
            context.messages.append({"role": "system", "content": content})


class OutfitPersistenceProvider(BaseTurnContextProvider):
    """Flush streamed outfit transitions into SqliteSessionStore right after assistant turn row append."""

    capability_id = "outfit_persistence"

    def __init__(self, controller: OutfitRuntimeController) -> None:
        self.controller = controller

    def message_added(self, context: MessageAddedContext) -> None:
        if context.role == "assistant":
            self.controller.flush_pending_to_store()


class OutfitSessionCapability(BaseSessionCapability):
    """Own per-session `OutfitRuntimeController`, prompt context, and outfit commands."""

    capability_id = "outfit"

    def __init__(self) -> None:
        self.controller = OutfitRuntimeController()
        self._before_provider = OutfitBeforeChatProvider(self.controller)
        self._persistence_provider: OutfitPersistenceProvider | None = None

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        history_arg = str(getattr(context.args, "history", "") or "").strip()
        media_mode = str(
            getattr(context.args, "media_selection_mode", "indexed") or "indexed"
        )
        raw_auto = getattr(context.args, "auto_outfit_switch", None)
        auto_arg = raw_auto if isinstance(raw_auto, bool) else None
        initial_outfits_raw = str(
            getattr(context.args, "initial_outfits", "") or ""
        ).strip()

        self.controller.initialize(
            context.config,
            history_arg=history_arg,
            media_selection_mode=media_mode,
            auto_outfit_switch_arg=auto_arg,
            initial_outfits_raw=initial_outfits_raw,
            character_names=context.character_names,
        )
        initial_path = str(getattr(context.args, "init_sprite_path", "") or "")
        if initial_path:
            context.args.init_sprite_path = self.controller.resolve_initial_sprite_path(initial_path)
        if history_arg and self.controller.has_any_multi_group_character():
            self._persistence_provider = OutfitPersistenceProvider(self.controller)
        else:
            self._persistence_provider = None

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None:
        self.controller.bind_runtime(
            transport=context.transport if context.mode == "stream" else None,
            ui_updates=context.ui_updates,
        )
        if context.app_runtime is not None:
            try:
                context.app_runtime.outfit_controller = self.controller
            except Exception:
                pass
        if context.mode == "stream":
            self.controller.emit_state()

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        if self._persistence_provider is not None:
            return (self._before_provider, self._persistence_provider)
        return (self._before_provider,)

    def command_handlers(self) -> Mapping[str, Callable[[object], None]]:
        return {
            "set-character-outfit": self._handle_set_character_outfit,
            "set-auto-outfit-switch": self._handle_set_auto_outfit_switch,
        }

    def _handle_set_character_outfit(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("set-character-outfit payload must be an object.")
        cname = str(
            payload.get("characterName") or payload.get("name") or ""
        ).strip()
        raw_group = payload.get("group")
        if raw_group is None and "activeGroup" in payload:
            raw_group = payload.get("activeGroup")
        group = str(raw_group).strip() if isinstance(raw_group, str) else None
        locked = (
            bool(payload["locked"])
            if isinstance(payload.get("locked"), bool)
            else None
        )
        self.controller.set_character_outfit(cname, group=group, locked=locked)

    def _handle_set_auto_outfit_switch(self, payload: object) -> None:
        if isinstance(payload, bool):
            enabled = payload
        elif isinstance(payload, Mapping) and isinstance(payload.get("enabled"), bool):
            enabled = bool(payload["enabled"])
        elif isinstance(payload, Mapping) and isinstance(
            payload.get("autoOutfitSwitch"), bool
        ):
            enabled = bool(payload["autoOutfitSwitch"])
        else:
            raise ValueError("set-auto-outfit-switch requires a boolean enabled field.")
        self.controller.set_auto_outfit_switch_enabled(enabled)

    def on_shutdown(self) -> None:
        self.controller.flush_pending_to_store()
        self.controller.bind_runtime(transport=None, ui_updates=None)

"""Persistence target abstractions decoupling character operations from storage backends."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any, Protocol, runtime_checkable

from config.schema import Character, SELF_PERSONA_NAME


class CharacterProfileError(ValueError):
    """Domain validation or uniqueness conflict raised during character mutations."""


@runtime_checkable
class CharacterPersistenceTarget(Protocol):
    """Minimal storage contract consumed by domain character operations."""

    def get_by_id(self, char_id: str) -> Character | None: ...

    def get_by_name(self, name: str) -> Character | None: ...

    def list_all(self) -> Sequence[Character]: ...

    def ensure_self_persona(self) -> Character: ...

    def save_character(self, character: Character) -> None: ...

    def delete_character_record(self, character: Character) -> bool: ...


def _sync_pydantic_model_in_place(target: Any, source: Any) -> None:
    """Copy fields from ``source`` onto ``target`` preserving callers' object identity."""
    target.__dict__.clear()
    target.__dict__.update(deepcopy(source.__dict__))
    fields_set = getattr(source, "__pydantic_fields_set__", None)
    if fields_set is not None and hasattr(target, "__pydantic_fields_set__"):
        object.__setattr__(target, "__pydantic_fields_set__", set(fields_set))


class ConfigManagerCharacterTarget:
    """Adapter backing ``CharacterPersistenceTarget`` with a ``ConfigManager`` or test double."""

    def __init__(
        self,
        config_manager: Any,
        *,
        save_fn: Callable[[], None] | None = None,
    ) -> None:
        self._cm = config_manager
        self._save_fn = save_fn or config_manager.save_characters_config
        self._seen_by_id: dict[str, Character] = {}

    def _remember(self, character: Character | None) -> Character | None:
        if character is not None:
            char_id = str(getattr(character, "id", "") or "").strip()
            if char_id:
                self._seen_by_id[char_id] = character
        return character

    def _characters_list(self) -> list[Character] | None:
        try:
            chars = self._cm.config.characters
        except Exception:
            return None
        return chars if isinstance(chars, list) else None

    def list_all(self) -> list[Character]:
        chars = self._characters_list()
        if chars is not None:
            return list(chars)
        return list(self._seen_by_id.values())

    def get_by_id(self, char_id: str) -> Character | None:
        cleaned = str(char_id or "").strip()
        if not cleaned:
            return None
        for item in self.list_all():
            if str(getattr(item, "id", "") or "") == cleaned:
                return self._remember(item)
        return self._seen_by_id.get(cleaned)

    def get_by_name(self, name: str) -> Character | None:
        return self._remember(self._cm.get_character_by_name(name))

    def ensure_self_persona(self) -> Character:
        ensure_fn = getattr(self._cm, "ensure_self_persona_persisted", None)
        if callable(ensure_fn):
            return self._remember(ensure_fn())  # type: ignore[return-value]
        return self._remember(self._cm.get_character_by_name(SELF_PERSONA_NAME))  # type: ignore[return-value]

    def _find_list_entry(self, chars: list[Character], character: Character) -> Character | None:
        target_id = getattr(character, "id", None)
        for item in chars:
            if item is character or (target_id and getattr(item, "id", None) == target_id):
                return item
        for item in chars:
            if getattr(item, "name", None) == character.name:
                return item
        return None

    def save_character(self, character: Character) -> None:
        chars = self._characters_list()
        if chars is not None:
            existing = self._find_list_entry(chars, character)
        else:
            char_id = str(getattr(character, "id", "") or "").strip()
            existing = (self._seen_by_id.get(char_id) if char_id else None) or self.get_by_name(character.name)
        if existing is not None:
            prev_dict = dict(existing.__dict__)
            prev_fields = (
                set(existing.__pydantic_fields_set__)
                if hasattr(existing, "__pydantic_fields_set__")
                else None
            )
            _sync_pydantic_model_in_place(existing, character)
            try:
                self._save_fn()
            except Exception as exc:
                if not getattr(exc, "published", False):
                    existing.__dict__.clear()
                    existing.__dict__.update(prev_dict)
                    if prev_fields is not None:
                        object.__setattr__(existing, "__pydantic_fields_set__", prev_fields)
                raise
            return

        if chars is None:
            self._save_fn()
            return

        chars.append(character)
        try:
            self._save_fn()
        except Exception as exc:
            if not getattr(exc, "published", False):
                try:
                    chars.remove(character)
                except ValueError:
                    pass
            raise

    def delete_character_record(self, character: Character) -> bool:
        chars = self._characters_list()
        if chars is None:
            return False
        existing = self._find_list_entry(chars, character)
        if existing is None:
            return False
        chars.remove(existing)
        try:
            self._save_fn()
        except Exception as exc:
            if not getattr(exc, "published", False):
                chars.append(existing)
            raise
        return True


__all__ = [
    "CharacterPersistenceTarget",
    "CharacterProfileError",
    "ConfigManagerCharacterTarget",
]

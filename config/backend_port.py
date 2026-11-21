"""Narrow storage backend port consumed by ``ConfigManager`` without importing ``core``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from config.models import ApiConfig, Background, Character, Effect, SystemConfig


@runtime_checkable
class ConfigBackendPort(Protocol):
    """Port implemented by ``AppStoresConfigBackend`` and bound at composition roots."""

    @property
    def characters_revision(self) -> str:
        """Opaque revision token incremented when persisted characters change."""

    def load_api_config(self) -> ApiConfig: ...

    def save_api_config(self, value: ApiConfig) -> None: ...

    def load_system_config(self) -> SystemConfig: ...

    def save_system_config(self, value: SystemConfig) -> None: ...

    def list_characters(self) -> list[Character]: ...

    def save_characters(self, items: Sequence[Character]) -> str: ...

    def get_character_by_name(self, name: str) -> Character | None: ...

    def ensure_self_persona(self) -> Character: ...

    def list_backgrounds(self) -> list[Background]: ...

    def save_backgrounds(self, items: Sequence[Background]) -> str: ...

    def list_effects(self) -> list[Effect]: ...

    def save_effects(self, items: Sequence[Effect]) -> str: ...


__all__ = ["ConfigBackendPort"]

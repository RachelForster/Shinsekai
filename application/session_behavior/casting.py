"""Cast binding resolution for selective sprite/TTS driving and unbound NPC passthrough."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CastBinding:
    """Binding from a story/document speaker role to an existing host character asset."""

    character_name: str
    aliases: tuple[str, ...] = ()
    role: str = "supporting"
    silhouette_until_revealed: bool = False
    revealed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "characterName": self.character_name,
            "aliases": list(self.aliases),
            "role": self.role,
            "silhouetteUntilRevealed": self.silhouette_until_revealed,
            "revealed": self.revealed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CastBinding:
        raw_aliases = data.get("aliases") or ()
        aliases = tuple(
            cleaned
            for item in raw_aliases
            if (cleaned := str(item or "").strip())
        )
        return cls(
            character_name=str(data["characterName"]).strip(),
            aliases=aliases,
            role=str(data.get("role") or "supporting").strip() or "supporting",
            silhouette_until_revealed=bool(data.get("silhouetteUntilRevealed", False)),
            revealed=bool(data.get("revealed", True)),
        )


class CastingMap:
    """Resolve runtime speaker names to bound host characters or identify unbound NPCs."""

    def __init__(self, bindings: Sequence[CastBinding] = ()) -> None:
        self._bindings: tuple[CastBinding, ...] = tuple(
            binding
            for binding in bindings
            if str(binding.character_name or "").strip()
        )
        self._exact: dict[str, CastBinding] = {}
        self._casefold: dict[str, CastBinding] = {}
        for binding in self._bindings:
            names = (binding.character_name, *binding.aliases)
            for name in names:
                clean = str(name or "").strip()
                if not clean:
                    continue
                self._exact.setdefault(clean, binding)
                self._casefold.setdefault(clean.casefold(), binding)

    @property
    def bindings(self) -> tuple[CastBinding, ...]:
        return self._bindings

    def resolve(self, speaker_name: str, *, cc: Any = None) -> CastBinding | None:
        """Look up a speaker via exact match, trimmed casefold match, or OpenCC."""
        raw = str(speaker_name or "").strip()
        if not raw:
            return None
        hit = self._exact.get(raw) or self._casefold.get(raw.casefold())
        if hit is not None:
            return hit
        if cc is None:
            return None
        convert = getattr(cc, "convert", None)
        if not callable(convert):
            return None
        converted_raw = str(convert(raw) or "").strip()
        if converted_raw:
            hit = (
                self._exact.get(converted_raw)
                or self._casefold.get(converted_raw.casefold())
            )
            if hit is not None:
                return hit
        for key, binding in self._exact.items():
            if str(convert(key) or "").strip().casefold() == converted_raw.casefold():
                return binding
        return None

    def is_bound(self, speaker_name: str, *, cc: Any = None) -> bool:
        return self.resolve(speaker_name, cc=cc) is not None

    def speaker_requires_media(self, speaker_name: str, *, cc: Any = None) -> bool:
        """Return True iff the speaker is bound and therefore requires sprite/media output."""
        return self.is_bound(speaker_name, cc=cc)

    def bound_speaker_names(self) -> tuple[str, ...]:
        """Return deduplicated canonical names and aliases for repair prompts."""
        ordered: list[str] = []
        seen: set[str] = set()
        for binding in self._bindings:
            for name in (binding.character_name, *binding.aliases):
                clean = str(name or "").strip()
                if clean and clean not in seen:
                    seen.add(clean)
                    ordered.append(clean)
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bindings": [binding.to_dict() for binding in self._bindings],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CastingMap:
        raw_items: Iterable[Any] = data.get("bindings") or ()
        bindings = [
            CastBinding.from_dict(item)
            for item in raw_items
            if isinstance(item, Mapping) and str(item.get("characterName") or "").strip()
        ]
        return cls(bindings)


__all__ = [
    "CastBinding",
    "CastingMap",
]

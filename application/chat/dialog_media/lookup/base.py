"""Shared asset lookup contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AssetCandidate:
    """One currently configured asset that may be selected."""

    asset_id: str
    index: int
    value: Any
    path: str = ""
    tags: str = ""


@dataclass(frozen=True, slots=True)
class AssetIdMatch:
    """One strategy result, ordered ahead of less relevant matches."""

    asset_id: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class AssetLookupResult:
    """Ranked asset identifiers returned by a lookup strategy."""

    matches: tuple[AssetIdMatch, ...] = ()

    @property
    def best(self) -> AssetIdMatch | None:
        return self.matches[0] if self.matches else None


@dataclass(frozen=True, slots=True)
class AssetLookupRequest:
    """Inputs shared by direct-id and semantic asset lookup."""

    scope: str
    candidates: tuple[AssetCandidate, ...]
    explicit_asset_id: str = ""
    vibe: str = ""


class AssetLookupStrategy(ABC):
    """Rank configured asset identifiers for one media instruction."""

    @abstractmethod
    def lookup(self, request: AssetLookupRequest) -> AssetLookupResult:
        """Return zero or more matches in descending preference order."""

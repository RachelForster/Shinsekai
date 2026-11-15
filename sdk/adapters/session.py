"""Provider-neutral domain value objects and narrow SOLID port for chat sessions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sdk.adapters.memory import MemoryRepository

MEMORY_MODE_ISOLATED = "isolated"
MEMORY_MODE_SHARED = "shared"
MEMORY_MODE_INHERIT_READONLY = "inherit_readonly"

MemoryMode = Literal["isolated", "shared", "inherit_readonly"]
VALID_MEMORY_MODES: frozenset[str] = frozenset(
    {
        MEMORY_MODE_ISOLATED,
        MEMORY_MODE_SHARED,
        MEMORY_MODE_INHERIT_READONLY,
    }
)


def normalize_memory_mode(mode: str | None) -> MemoryMode:
    """Validate and normalize a session memory isolation mode."""
    cleaned = str(mode or MEMORY_MODE_SHARED).strip().lower()
    if cleaned not in VALID_MEMORY_MODES:
        raise ValueError(
            f"Unsupported memory_mode {mode!r}; expected one of {sorted(VALID_MEMORY_MODES)}"
        )
    return cleaned  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class OutfitState:
    """Per-character outfit group and manual lock state within one session."""

    character_name: str
    active_group: str = ""
    locked: bool = False
    updated_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class TurnNode:
    """Immutable full-fidelity turn stored in append-only session history."""

    seq: int = 0
    branch_id: str = "main"
    turn_id: str = ""
    role: str = ""
    speaker: str = ""
    raw_message: Mapping[str, Any] = field(default_factory=dict)
    rendered_html: str = ""
    plain_text: str = ""
    voice_id: str = ""
    attachments: tuple[Mapping[str, Any], ...] = ()
    source: str = "user"
    outfit_snapshot: Mapping[str, OutfitState] = field(default_factory=dict)
    created_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class CompactCheckpoint:
    """Non-destructive rolling context summary anchored to a monotonic turn seq."""

    checkpoint_id: int = 0
    branch_id: str = "main"
    up_to_seq: int = 0
    rolling_summary: str = ""
    created_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class TruncateReport:
    """Atomic 4-in-1 cascade truncation result after revert or reroll."""

    kept_up_to_seq: int
    deleted_turns: int = 0
    deleted_checkpoints: int = 0
    rolled_back_save_memories: int = 0
    rolled_back_shared_memories: int = 0
    restored_outfits: Mapping[str, OutfitState] = field(default_factory=dict)

    @property
    def rolled_back_memories(self) -> int:
        return self.rolled_back_save_memories + self.rolled_back_shared_memories


@runtime_checkable
class ConversationSessionPort(Protocol):
    """Single-responsibility port for durable turn trees, checkpoints, and cascade rollback."""

    @property
    def session_id(self) -> str:
        """Stable canonical identifier for this conversation save."""

    @property
    def save_memory_repo(self) -> MemoryRepository:
        """Per-save isolated MemoryRepository bound to this session."""

    def append_turn(self, turn: TurnNode) -> TurnNode:
        """Append one turn with a strictly monotonic sequence number."""

    def append_raw_message(
        self,
        message: Mapping[str, Any],
        *,
        branch_id: str = "main",
        outfit_snapshot: Mapping[str, OutfitState] | None = None,
    ) -> TurnNode:
        """Convert and append a raw LLM message dict onto branch_id."""

    def replace_turns(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        branch_id: str = "main",
    ) -> Sequence[TurnNode]:
        """Replace non-system turns on branch_id when reconciling an explicit branch snapshot."""

    def list_turns(
        self,
        *,
        branch_id: str = "main",
        after_seq: int = 0,
        up_to_seq: int | None = None,
    ) -> Sequence[TurnNode]:
        """List stored turns for branch_id in strictly ascending seq order."""

    def truncate_after(
        self,
        seq: int,
        *,
        branch_id: str = "main",
    ) -> TruncateReport:
        """Atomically truncate turns > seq, checkpoints > seq, memories > seq, and restore outfits."""

    def clear(self, *, branch_id: str | None = None) -> None:
        """Clear all turns, checkpoints, outfit states, and isolated memories (or one branch)."""

    def add_compact_checkpoint(
        self,
        *,
        up_to_seq: int,
        rolling_summary: str,
        branch_id: str = "main",
        created_at_ms: int | None = None,
    ) -> CompactCheckpoint:
        """Record a non-destructive rolling summary checkpoint without deleting turns."""

    def get_active_compact_checkpoint(
        self,
        *,
        branch_id: str = "main",
        max_seq: int | None = None,
    ) -> CompactCheckpoint | None:
        """Return the latest checkpoint covering up_to_seq <= max_seq (or latest overall)."""

    def list_compact_checkpoints(
        self,
        *,
        branch_id: str = "main",
    ) -> Sequence[CompactCheckpoint]:
        """Return all compact checkpoints for branch_id ordered by up_to_seq ascending."""

    def build_active_llm_messages(
        self,
        *,
        system_prompt: str | None = None,
        branch_id: str = "main",
        max_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble active LLM prompt context from checkpoint summary + full turns after up_to_seq."""

    def get_memory_mode(self) -> MemoryMode:
        """Return the memory isolation mode configured for this save."""

    def set_memory_mode(self, mode: MemoryMode) -> None:
        """Persist the memory isolation mode for this save."""

    def get_auto_outfit_switch(self) -> bool:
        """Return whether automatic outfit group switching is enabled for this save."""

    def set_auto_outfit_switch(self, enabled: bool) -> None:
        """Persist whether automatic outfit group switching is enabled for this save."""

    def get_outfit_state(self, character_name: str) -> OutfitState | None:
        """Return the current outfit state for character_name, or None if unset."""

    def list_outfit_states(self) -> Mapping[str, OutfitState]:
        """Return all persisted character outfit states in this session."""

    def set_outfit_state(self, state: OutfitState) -> None:
        """Persist the current outfit state for state.character_name."""

    def close(self) -> None:
        """Release any underlying file handles or pooled connections."""


SessionStoreFactory = Callable[[str], ConversationSessionPort]
SessionStoreAvailabilityProbe = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class SessionStoreContribution:
    """Plugin contribution registering a custom ConversationSessionPort backend."""

    provider: str
    factory: SessionStoreFactory
    available: SessionStoreAvailabilityProbe = lambda: True
    priority: int = 100


__all__ = [
    "CompactCheckpoint",
    "ConversationSessionPort",
    "MEMORY_MODE_INHERIT_READONLY",
    "MEMORY_MODE_ISOLATED",
    "MEMORY_MODE_SHARED",
    "MemoryMode",
    "OutfitState",
    "SessionStoreAvailabilityProbe",
    "SessionStoreContribution",
    "SessionStoreFactory",
    "TruncateReport",
    "TurnNode",
    "VALID_MEMORY_MODES",
    "normalize_memory_mode",
]

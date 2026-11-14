"""Provider-neutral domain value objects and narrow SOLID ports for memory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

SCOPE_SELF_PUBLIC = "self_public"
SCOPE_CHAR_CANON = "char_canon"
SCOPE_CHAR_CROSS_SAVE = "char_cross_save"
SCOPE_SAVE_ISOLATED = "save_isolated"

NAMESPACE_KNOWLEDGE = "knowledge"
NAMESPACE_MEDIA_ASSET = "media_asset"

MemoryScope = Literal["self_public", "char_canon", "char_cross_save", "save_isolated"]
MemoryKind = Literal["profile", "episodic", "promise", "canon"]
ClarityTier = Literal["clear", "faded", "dormant", "canon"]
ReadinessState = Literal["ready", "loading", "not_started", "error", "missing_dependency"]


@dataclass(frozen=True, slots=True)
class ReadinessStatus:
    """Availability snapshot reported by an embedding or memory backend."""

    state: ReadinessState
    model_cached: bool = False
    message: str = ""
    module_name: str = ""
    package_name: str = ""


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """Immutable domain entity representing one stored memory record."""

    id: str
    scope: str
    owner_id: str
    detail_text: str
    gist_text: str = ""
    slot_key: str = ""
    kind: str = "episodic"
    topic_tags: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    importance: float = 0.5
    pinned: bool = False
    created_at: float = 0.0
    event_at: float | None = None
    last_recalled_at: float = 0.0
    recall_count: int = 0
    superseded_by: str | None = None
    source_session_id: str = ""
    source_turn_seq: int | None = None
    embedding: Any | None = None


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    """Extracted memory candidate prior to embedding and persistence."""

    owner_id: str
    detail_text: str
    gist_text: str = ""
    scope: str = SCOPE_CHAR_CROSS_SAVE
    slot_key: str = ""
    kind: str = "episodic"
    topic_tags: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    importance: float = 0.5
    pinned: bool = False
    event_at: float | None = None
    source_session_id: str = ""
    source_turn_seq: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryScopeFilter:
    """Orthogonal scope and metadata predicates for repository queries."""

    scopes: tuple[str, ...] = ()
    owner_ids: tuple[str, ...] = ()
    session_id: str | None = None
    max_turn_seq: int | None = None
    include_superseded: bool = False
    only_pinned: bool | None = None
    event_from: float | None = None
    event_to: float | None = None


@dataclass(frozen=True, slots=True)
class MemoryCandidateQuery:
    """Hybrid vector + full-text candidate query specification."""

    scope_filter: MemoryScopeFilter = field(default_factory=MemoryScopeFilter)
    query_vectors: tuple[Any, ...] = ()
    keyword_query: str = ""
    limit: int = 20


@dataclass(frozen=True, slots=True)
class CandidateHit:
    """Raw hybrid retrieval hit before retention scoring."""

    record: MemoryRecord
    vector_score: float = 0.0
    fts_score: float = 0.0


@dataclass(frozen=True, slots=True)
class RetentionState:
    """Evaluated retention score and dual-granularity presentation state."""

    retention: float
    tier: ClarityTier
    rendered_text: str


@dataclass(frozen=True, slots=True)
class TurnRecallInput:
    """Per-turn context supplied to the recall planner and orchestrator."""

    user_text: str
    previous_assistant_text: str = ""
    active_character_names: tuple[str, ...] = ()
    session_id: str = ""
    memory_mode: str = "shared"
    source: str = "user"
    now_ts: float = 0.0
    seconds_since_last_turn: float = 0.0
    in_window_turn_seqs: frozenset[int] = frozenset()
    recently_injected_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RecallPlan:
    """Planned query clauses, temporal bounds, and gating decision."""

    should_recall: bool
    is_session_wakeup: bool = False
    query_clauses: tuple[str, ...] = ()
    keyword_query: str = ""
    event_from: float | None = None
    event_to: float | None = None
    limit: int = 8


@dataclass(frozen=True, slots=True)
class MemoryContextBlock:
    """Formatted memory block injected ephemerally into one LLM request."""

    rendered: str
    recalled_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionWindow:
    """Dialogue turn slice submitted to a memory extractor."""

    messages: tuple[Mapping[str, Any], ...]
    character_names: tuple[str, ...]
    now_iso: str
    session_id: str = ""
    turn_seq: int | None = None


@dataclass(frozen=True, slots=True)
class IngestReport:
    """Result summary after deduplicating and persisting memory drafts."""

    added_ids: tuple[str, ...] = ()
    superseded_ids: tuple[str, ...] = ()
    skipped_duplicates: int = 0


@dataclass(frozen=True, slots=True)
class VectorSliceEntry:
    """Static vector slice used by knowledge bases and tagged media catalogs."""

    id: str
    namespace: str
    scope_id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    embedding: Any | None = None


@dataclass(frozen=True, slots=True)
class VectorSliceHit:
    """Scored match from a static vector slice namespace."""

    entry: VectorSliceEntry
    vector_score: float = 0.0
    fts_score: float = 0.0
    score: float = 0.0


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Single-responsibility port for text embedding generation."""

    @property
    def dimensions(self) -> int:
        """Dimensionality of normalized float32 output vectors."""

    def embed_query(self, text: str) -> np.ndarray:
        """Encode a single search query into a normalized 1D float32 vector."""

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """Encode a batch of documents into a normalized (N, D) float32 matrix."""

    def status(self) -> ReadinessStatus:
        """Return non-blocking readiness information for UI status polling."""


@runtime_checkable
class MemoryRepository(Protocol):
    """Single-responsibility storage and hybrid candidate retrieval port."""

    def upsert(self, record: MemoryRecord) -> str:
        """Insert or update a memory record, superseding matching slot_key entries."""

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Fetch one memory record by ID, or None if absent."""

    def search_candidates(self, query: MemoryCandidateQuery) -> Sequence[CandidateHit]:
        """Retrieve hybrid vector + FTS candidates matching the scope filter."""

    def expand_entities(
        self,
        entities: Sequence[str],
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 10,
    ) -> Sequence[MemoryRecord]:
        """Perform 1-hop entity expansion within the permitted scope."""

    def list_by_scope(
        self,
        scope_filter: MemoryScopeFilter,
        *,
        limit: int = 200,
    ) -> Sequence[MemoryRecord]:
        """List memories matching the given scope filter."""

    def record_recall(self, memory_ids: Sequence[str], *, recalled_at: float) -> int:
        """Increment recall_count and update last_recalled_at for recalled IDs."""

    def rollback_after_turn(self, session_id: str, turn_seq: int) -> int:
        """Delete unpinned memories created after turn_seq and restore superseded slots."""

    def set_pinned(self, memory_id: str, pinned: bool) -> bool:
        """Pin or unpin a memory record so it does not decay or roll back."""

    def delete(self, memory_id: str) -> bool:
        """Delete one memory record by ID and restore any record it superseded."""


@runtime_checkable
class StaticVectorStorePort(Protocol):
    """Segregated port for static vector slices (knowledge bases & media assets)."""

    def upsert_slices(self, entries: Sequence[VectorSliceEntry]) -> int:
        """Insert or replace static vector slices in batch."""

    def search_slices(
        self,
        *,
        namespace: str,
        scope_ids: Sequence[str],
        query_vector: Any | None = None,
        keyword_query: str = "",
        metadata_filter: Mapping[str, Any] | None = None,
        limit: int = 10,
    ) -> Sequence[VectorSliceHit]:
        """Rank slices within one namespace and one or more scope_ids."""

    def list_slices(
        self,
        *,
        namespace: str,
        scope_id: str | None = None,
        metadata_filter: Mapping[str, Any] | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> Sequence[VectorSliceEntry]:
        """Browse slices in deterministic order without loading dense vectors."""

    def count_by_scope(self, *, namespace: str) -> Mapping[str, int]:
        """Return entry counts grouped by scope_id for a namespace."""

    def delete_slice(self, *, namespace: str, slice_id: str) -> bool:
        """Delete one static slice by ID."""

    def delete_scope(self, *, namespace: str, scope_id: str) -> int:
        """Delete all slices belonging to one scope_id and return deleted count."""


@runtime_checkable
class RetentionPolicy(Protocol):
    """Single-responsibility port for temporal decay and clarity evaluation."""

    def evaluate(self, record: MemoryRecord, *, now_ts: float) -> RetentionState:
        """Evaluate retention score and clarity tier at timestamp now_ts."""


@runtime_checkable
class RecallPlanner(Protocol):
    """Single-responsibility port for recall gating and query decomposition."""

    def plan(self, turn_input: TurnRecallInput) -> RecallPlan:
        """Build a zero-latency recall plan from the current turn context."""


@runtime_checkable
class MemoryExtractorPort(Protocol):
    """Single-responsibility port for extracting structured memory drafts."""

    def extract(self, window: ExtractionWindow) -> Sequence[MemoryDraft]:
        """Extract structured memory drafts from a slice of dialogue turns."""


EmbeddingProviderFactory = Callable[[], EmbeddingProvider]
MemoryRepositoryFactory = Callable[[], MemoryRepository]
MemoryAvailabilityProbe = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class EmbeddingProviderContribution:
    """Plugin contribution registering a custom EmbeddingProvider implementation."""

    provider: str
    factory: EmbeddingProviderFactory
    available: MemoryAvailabilityProbe = lambda: True
    priority: int = 100


@dataclass(frozen=True, slots=True)
class MemoryRepositoryContribution:
    """Plugin contribution registering a custom MemoryRepository implementation."""

    provider: str
    factory: MemoryRepositoryFactory
    available: MemoryAvailabilityProbe = lambda: True
    priority: int = 100


__all__ = [
    "CandidateHit",
    "ClarityTier",
    "EmbeddingProvider",
    "EmbeddingProviderContribution",
    "EmbeddingProviderFactory",
    "ExtractionWindow",
    "IngestReport",
    "MemoryAvailabilityProbe",
    "MemoryCandidateQuery",
    "MemoryContextBlock",
    "MemoryDraft",
    "MemoryExtractorPort",
    "MemoryKind",
    "MemoryRecord",
    "MemoryRepository",
    "MemoryRepositoryContribution",
    "MemoryRepositoryFactory",
    "MemoryScope",
    "MemoryScopeFilter",
    "NAMESPACE_KNOWLEDGE",
    "NAMESPACE_MEDIA_ASSET",
    "ReadinessState",
    "ReadinessStatus",
    "RecallPlan",
    "RecallPlanner",
    "RetentionPolicy",
    "RetentionState",
    "SCOPE_CHAR_CANON",
    "SCOPE_CHAR_CROSS_SAVE",
    "SCOPE_SAVE_ISOLATED",
    "SCOPE_SELF_PUBLIC",
    "StaticVectorStorePort",
    "TurnRecallInput",
    "VectorSliceEntry",
    "VectorSliceHit",
]

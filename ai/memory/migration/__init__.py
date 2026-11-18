"""Zero-dependency migration from legacy local Qdrant SQLite storage."""

from __future__ import annotations

from ai.memory.migration.errors import (
    LegacyQdrantDecodeError,
    LegacyQdrantMigrationError,
    LegacyQdrantReadError,
    UnsafeLegacyQdrantDataError,
)
from ai.memory.migration.knowledge_runner import (
    migrate_legacy_knowledge_qdrant,
    migrate_legacy_knowledge_qdrant_explicit,
)
from ai.memory.migration.memory_runner import (
    migrate_legacy_memory_qdrant,
    migrate_legacy_memory_qdrant_explicit,
)
from ai.memory.migration.qdrant_reader import (
    QdrantCollectionReadResult,
    get_knowledge_migration_status,
    get_memory_migration_status,
    iter_legacy_qdrant_points,
    read_legacy_qdrant_collection,
)
from ai.memory.migration.unpickler import (
    _QdrantSafeUnpickler,
    _TrustedLegacyQdrantUnpickler,
    decode_legacy_qdrant_point,
)

__all__ = [
    "LegacyQdrantDecodeError",
    "LegacyQdrantMigrationError",
    "LegacyQdrantReadError",
    "QdrantCollectionReadResult",
    "UnsafeLegacyQdrantDataError",
    "_QdrantSafeUnpickler",
    "_TrustedLegacyQdrantUnpickler",
    "decode_legacy_qdrant_point",
    "get_knowledge_migration_status",
    "get_memory_migration_status",
    "iter_legacy_qdrant_points",
    "migrate_legacy_knowledge_qdrant",
    "migrate_legacy_knowledge_qdrant_explicit",
    "migrate_legacy_memory_qdrant",
    "migrate_legacy_memory_qdrant_explicit",
    "read_legacy_qdrant_collection",
]

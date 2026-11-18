"""Exception hierarchy for legacy local Qdrant migration."""

from __future__ import annotations

import pickle


class LegacyQdrantMigrationError(RuntimeError):
    """Base error for legacy local Qdrant migration failures."""


class LegacyQdrantReadError(LegacyQdrantMigrationError):
    """Raised when a legacy Qdrant SQLite database cannot be opened or queried."""


class LegacyQdrantDecodeError(LegacyQdrantMigrationError):
    """Raised when a legacy Qdrant point row is malformed or cannot be decoded."""


class UnsafeLegacyQdrantDataError(pickle.UnpicklingError, LegacyQdrantDecodeError):
    """Raised when a legacy Qdrant pickle references an unsupported or unsafe global."""

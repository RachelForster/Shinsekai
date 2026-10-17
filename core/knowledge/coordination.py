"""Shared synchronization for knowledge operations in the store-owning process."""

import threading


# Reentrant for imports and deletion workflows that call individually locked operations.
knowledge_operation_lock = threading.RLock()

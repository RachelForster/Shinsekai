"""Compatibility alias for template-session persistence."""

from __future__ import annotations

import sys

from application.chat import session_store as _implementation

sys.modules[__name__] = _implementation

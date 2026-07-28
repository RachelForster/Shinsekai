"""Compatibility alias for :mod:`application.chat.session_store`."""

from __future__ import annotations

import sys

from application.chat import session_store as _session_store

sys.modules[__name__] = _session_store

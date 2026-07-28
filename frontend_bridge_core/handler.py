"""Compatibility alias for the HTTP API route handler.

The transport entry point intentionally stays tiny. Route dispatch lives in
``frontend_bridge_core.routes.api`` and application orchestration lives under
``application``.
"""

from __future__ import annotations

import sys

from frontend_bridge_core.routes import api as _api

sys.modules[__name__] = _api

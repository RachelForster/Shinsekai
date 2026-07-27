"""Compatibility alias for :mod:`application.model_assets.service`."""

from __future__ import annotations

import sys

from application.model_assets import service as _service

sys.modules[__name__] = _service

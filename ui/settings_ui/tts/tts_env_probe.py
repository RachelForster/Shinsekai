"""Compatibility alias for :mod:`core.model_assets.tts_environment`."""

from __future__ import annotations

import sys

from core.model_assets import tts_environment as _environment

sys.modules[__name__] = _environment

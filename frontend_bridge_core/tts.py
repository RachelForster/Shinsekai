"""Compatibility alias for :mod:`application.model_assets.tts_bundle`."""

from __future__ import annotations

import sys

from application.model_assets import tts_bundle as _tts_bundle

sys.modules[__name__] = _tts_bundle

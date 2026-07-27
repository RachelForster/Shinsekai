"""Compatibility alias for :mod:`core.model_assets.tts_bundle_manifest`."""

from __future__ import annotations

import sys

from core.model_assets import tts_bundle_manifest as _manifest

sys.modules[__name__] = _manifest

"""Compatibility facade re-exporting built-in text-to-image adapters."""

from __future__ import annotations

import requests  # noqa: F401 - preserved for monkeypatches targeting ai.t2i.t2i_adapter.requests
import subprocess  # noqa: F401 - preserved for monkeypatches targeting ai.t2i.t2i_adapter.subprocess
import time  # noqa: F401 - preserved for monkeypatches targeting ai.t2i.t2i_adapter.time

from ai.t2i.adapters.comfyui import ComfyUIT2IAdapter
from ai.t2i.adapters.stable_diffusion import StableDiffusionAdapter
from sdk.adapters.t2i import T2IAdapter

__all__ = [
    "ComfyUIT2IAdapter",
    "StableDiffusionAdapter",
    "T2IAdapter",
]

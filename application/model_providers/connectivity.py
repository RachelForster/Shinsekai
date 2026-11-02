"""Provider connection checks using the settings currently being edited."""

from __future__ import annotations

from typing import Any


def check_comfyui_connection(base_url: str) -> dict[str, Any]:
    from ai.t2i.comfyui_connection import probe_comfyui_connection

    return probe_comfyui_connection(base_url)

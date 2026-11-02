"""Read-only ComfyUI API checks shared by setup and generation."""

from __future__ import annotations

from typing import Literal, TypedDict
from urllib.parse import urlsplit

import requests


class ComfyUIConnectionResult(TypedDict, total=False):
    ok: bool
    code: Literal[
        "connected",
        "invalid_url",
        "timeout",
        "unreachable",
        "auth_required",
        "http_error",
        "not_comfyui",
        "tls_error",
    ]
    httpStatus: int
    serverVersion: str


def probe_comfyui_connection(
    api_url: str, *, timeout: float = 10
) -> ComfyUIConnectionResult:
    """Check the API without initializing an adapter, launching it, or generating media."""
    base_url = api_url.strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        if (
            any(ord(char) < 32 or ord(char) == 127 for char in base_url)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or any(char.isspace() for char in parsed.hostname)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (parsed.port is not None and parsed.port == 0)
        ):
            return {"ok": False, "code": "invalid_url"}
    except ValueError:
        return {"ok": False, "code": "invalid_url"}

    try:
        response = requests.get(
            base_url + "/system_stats", timeout=timeout, allow_redirects=False
        )
    except requests.exceptions.Timeout:
        return {"ok": False, "code": "timeout"}
    except requests.exceptions.SSLError:
        return {"ok": False, "code": "tls_error"}
    except requests.exceptions.RequestException:
        return {"ok": False, "code": "unreachable"}

    status = response.status_code
    if status in {401, 403}:
        return {"ok": False, "code": "auth_required", "httpStatus": status}
    if 300 <= status < 400:
        return {"ok": False, "code": "not_comfyui", "httpStatus": status}
    if status != 200:
        return {"ok": False, "code": "http_error", "httpStatus": status}
    try:
        data = response.json()
    except ValueError:
        return {"ok": False, "code": "not_comfyui"}
    if not (
        isinstance(data, dict)
        and isinstance(data.get("system"), dict)
        and isinstance(data.get("devices"), list)
    ):
        return {"ok": False, "code": "not_comfyui"}

    result: ComfyUIConnectionResult = {"ok": True, "code": "connected"}
    version = data["system"].get("comfyui_version")
    if isinstance(version, str) and version.strip():
        result["serverVersion"] = version.strip()[:128]
    return result

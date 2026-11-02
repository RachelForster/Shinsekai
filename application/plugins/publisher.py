"""Application facade for plugin publishing use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def scan_local_plugin(path: str | Path) -> dict[str, Any]:
    from plugin_system.publisher.metadata import scan_local_plugin as _scan

    return _scan(path)


def submission_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from plugin_system.publisher.submission import submission_payload as _payload

    return _payload(payload)


def build_issue_url(payload: dict[str, Any]) -> str:
    from plugin_system.publisher.submission import build_issue_url as _build

    return _build(payload)


def default_submit_url() -> str:
    from plugin_system.publisher.submission import default_submit_url as _default

    return _default()


def validation_errors(payload: dict[str, Any]) -> list[str]:
    from plugin_system.publisher.validate import validation_errors as _errors

    return _errors(payload)

"""Pure validation rules for persisted network proxy configuration."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def normalize_proxy_url(
    value: Any,
    *,
    allowed_schemes: set[str],
    field_name: str,
) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in allowed_schemes or not parsed.netloc:
        allowed = "/".join(sorted(allowed_schemes))
        example_scheme = next(iter(sorted(allowed_schemes)))
        raise ValueError(
            f"{field_name} must be a {allowed} URL, "
            f"for example {example_scheme}://127.0.0.1:7890"
        )
    return raw

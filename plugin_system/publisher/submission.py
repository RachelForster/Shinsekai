from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .validate import normalize_submission


ISSUE_TEMPLATE = "PLUGIN_PUBLISH.yml"
ISSUE_FORM_PLUGIN_INFO_FIELD = "plugin-info"
UPSTREAM_SUBMIT_URL = f"https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new?template={ISSUE_TEMPLATE}"
STAGING_SUBMIT_URL = f"https://github.com/End0rph1nww/Shinsekai-Plugin-Registry/issues/new?template={ISSUE_TEMPLATE}"


def default_submit_url() -> str:
    configured = os.environ.get("SHINSEKAI_PLUGIN_SUBMIT_URL", "").strip()
    if configured:
        return configured
    target = os.environ.get("SHINSEKAI_PLUGIN_SUBMIT_TARGET", "").strip().lower()
    if target in {"fork", "staging", "dev", "development"}:
        return STAGING_SUBMIT_URL
    return UPSTREAM_SUBMIT_URL


def submission_json(payload: dict[str, Any]) -> str:
    return json.dumps(normalize_submission(payload), ensure_ascii=False, indent=2)


def issue_body(payload: dict[str, Any]) -> str:
    return f"```json\n{submission_json(payload)}\n```\n"


def build_issue_url(payload: dict[str, Any], base_url: str | None = None) -> str:
    normalized = normalize_submission(payload)
    split = urlsplit(base_url or default_submit_url())
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.setdefault("template", ISSUE_TEMPLATE)
    query["title"] = f"[Plugin] {normalized['display_name']}"
    query.pop("body", None)
    query[ISSUE_FORM_PLUGIN_INFO_FIELD] = f"```json\n{json.dumps(normalized, ensure_ascii=False, indent=2)}\n```\n"
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def submission_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_submission(payload)
    json_text = json.dumps(normalized, ensure_ascii=False, indent=2)
    return {
        "json": json_text,
        "submission": normalized,
    }

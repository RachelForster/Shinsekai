from __future__ import annotations

from typing import Any

from core.plugins.publisher.metadata import scan_local_plugin
from core.plugins.publisher.submission import build_issue_url, default_submit_url, submission_payload
from core.plugins.publisher.validate import validation_errors


def _scan_local_plugin(body: dict[str, Any]) -> dict[str, Any]:
    return scan_local_plugin(str(body.get("path") or "."))


def _validate_plugin_submission(body: dict[str, Any]) -> dict[str, Any]:
    errors = validation_errors(body)
    result: dict[str, Any] = {"errors": errors, "ok": not errors}
    if not errors:
        result.update(submission_payload(body))
    return result


def _build_plugin_submission_issue_url(body: dict[str, Any]) -> dict[str, Any]:
    payload = submission_payload(body)
    payload["issueUrl"] = build_issue_url(body)
    payload["submitUrl"] = default_submit_url()
    return payload


def _copy_plugin_submission_json(body: dict[str, Any]) -> dict[str, Any]:
    payload = submission_payload(body)
    payload["clipboardText"] = payload["json"]
    payload["message"] = "Plugin submission JSON copied."
    return payload

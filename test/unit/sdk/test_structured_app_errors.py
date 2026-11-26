from __future__ import annotations

import json
import re
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from frontend_bridge_core.i18n_helpers import bridge_error, bridge_tr
from frontend_bridge_core.routes.http_handler import BridgeHttpHandler
from sdk.exception import AppError, download_error_from_exception

LOCALES_DIR = Path(__file__).resolve().parents[3] / "i18n" / "locales"
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


class _DummyHandler(BridgeHttpHandler):
    def __init__(self) -> None:
        self.captured: tuple[dict, HTTPStatus] | None = None

    def _send_json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:  # type: ignore[override]
        self.captured = (dict(data), status)


def _walk_leaf_entries(data: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_walk_leaf_entries(v, path))
        else:
            out[path] = str(v)
    return out


def test_app_error_serializes_error_code_and_params_on_http_handler() -> None:
    handler = _DummyHandler()
    exc = AppError(
        "theme_exists",
        {"id": "neon"},
        "Theme already exists: neon",
        http_status=409,
    )
    handler._send_exception_json(exc)
    assert handler.captured == (
        {
            "error": "Theme already exists: neon",
            "type": "AppError",
            "errorCode": "theme_exists",
            "errorParams": {"id": "neon"},
        },
        HTTPStatus.CONFLICT,
    )


def test_bridge_error_preserves_python_exception_type_and_localizes_by_state() -> None:
    en_state = SimpleNamespace(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(system_config=SimpleNamespace(ui_language="en"))
        )
    )
    ja_state = SimpleNamespace(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(system_config=SimpleNamespace(ui_language="ja"))
        )
    )

    exc = bridge_error(FileNotFoundError, en_state, "theme_not_found", id="custom-dark")
    assert isinstance(exc, FileNotFoundError)
    assert str(exc) == "Theme not found: custom-dark"

    handler = _DummyHandler()
    handler._send_exception_json(exc)
    assert handler.captured == (
        {
            "error": "Theme not found: custom-dark",
            "type": "FileNotFoundError",
            "errorCode": "theme_not_found",
            "errorParams": {"id": "custom-dark"},
        },
        HTTPStatus.NOT_FOUND,
    )

    assert bridge_tr(ja_state, "chat.already_running") == "チャットプロセスは既に実行中です。"


def test_download_error_exposes_reason_code_and_localized_user_message() -> None:
    class FakeHttpStatusError(Exception):
        status_code = 429
        url = "https://example.invalid/model.bin"

    zh_err = download_error_from_exception(FakeHttpStatusError("rate limited"), locale="zh_CN")
    en_err = download_error_from_exception(FakeHttpStatusError("rate limited"), locale="en")
    ja_err = download_error_from_exception(FakeHttpStatusError("rate limited"), locale="ja")

    assert zh_err["reasonCode"] == "rate_limited"
    assert en_err["reasonCode"] == "rate_limited"
    assert ja_err["reasonCode"] == "rate_limited"
    assert "请求过于频繁" in zh_err["userMessage"]
    assert "rate limited" in en_err["userMessage"].lower()
    assert "レート制限" in ja_err["userMessage"]


def test_python_locale_bundles_keep_exact_key_and_placeholder_parity_and_drop_dead_qt_sections() -> None:
    zh = json.loads((LOCALES_DIR / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
    ja = json.loads((LOCALES_DIR / "ja.json").read_text(encoding="utf-8"))

    removed_legacy_sections = {
        "template_gen",
        "nav",
        "plugins",
        "api",
        "char",
        "bg",
        "toolbar",
        "template",
        "tools",
    }
    assert removed_legacy_sections.isdisjoint(zh.keys())
    assert set(zh.keys()) == set(en.keys()) == set(ja.keys())

    zh_leaves = _walk_leaf_entries(zh)
    en_leaves = _walk_leaf_entries(en)
    ja_leaves = _walk_leaf_entries(ja)
    assert set(zh_leaves.keys()) == set(en_leaves.keys()) == set(ja_leaves.keys())

    for key, zh_val in zh_leaves.items():
        zh_p = set(PLACEHOLDER_RE.findall(zh_val))
        en_p = set(PLACEHOLDER_RE.findall(en_leaves[key]))
        ja_p = set(PLACEHOLDER_RE.findall(ja_leaves[key]))
        assert zh_p == en_p == ja_p, f"Placeholder mismatch on {key}: zh={zh_p} en={en_p} ja={ja_p}"

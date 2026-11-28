"""Tests for unified built-in format auto-discovery, localized labels, and plugin extensibility."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from ai.llm.formats import (
    JsonDialogFormat,
    RenpyDslDialogFormat,
    XmlTagsDialogFormat,
    XmlTagsStreamParser,
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
    discover_builtin_dialog_formats,
)
from ai.llm.template import PROMPT_CATALOG
from application.chat.dialog_formats import list_dialog_formats
from core.messaging.formats.registry import _reset_for_tests
from sdk.adapters.dialog_format import DialogFormatContribution, DialogOutputFormat
from sdk.lang import SUPPORTED_LANGS


@pytest.fixture(autouse=True)
def _restore_formats_registry():
    _reset_for_tests()
    configure_builtin_dialog_formats()
    yield
    _reset_for_tests()
    configure_builtin_dialog_formats()


def test_discover_builtin_dialog_formats_orders_all_three_formats() -> None:
    discovered = discover_builtin_dialog_formats()
    assert discovered == (
        XmlTagsDialogFormat,
        RenpyDslDialogFormat,
        JsonDialogFormat,
    )
    assert [(cls.order, cls.format_id) for cls in discovered] == [
        (10, "xml_v1"),
        (20, "renpy_v1"),
        (30, "json_v1"),
    ]


@pytest.mark.parametrize("locale", SUPPORTED_LANGS)
def test_builtin_format_labels_localize_without_frontend_hardcoding(locale: str) -> None:
    rows = list_dialog_formats(locale=locale)
    by_id = {row["id"]: row for row in rows}
    assert list(by_id)[:3] == ["xml_v1", "renpy_v1", "json_v1"]
    for fmt_id in ("xml_v1", "renpy_v1", "json_v1"):
        expected = PROMPT_CATALOG.translate(f"dialog.format_label_{fmt_id}", locale=locale)
        assert by_id[fmt_id] == {
            "id": fmt_id,
            "label": expected,
            "builtin": True,
        }


class _ExternalCustomPluginFormat(DialogOutputFormat):
    format_id = "external_markdown_v1"
    label = "Fallback Markdown Label"
    order = 40

    def render_label(self, *, locale: str = "zh_CN") -> str:
        return {
            "zh_CN": "外部 Markdown 对话格式",
            "en": "External Markdown Dialog",
            "ja": "外部 Markdown 対話形式",
        }.get(locale, self.label)

    def create_stream_parser(self) -> XmlTagsStreamParser:
        return XmlTagsStreamParser()

    def parse_complete(self, raw: str):
        return []

    def validate(self, raw: str) -> bool:
        return bool(raw.strip())


def test_external_plugin_format_integrates_with_localized_label_and_order() -> None:
    configure_registered_dialog_formats(
        [
            DialogFormatContribution(
                format_id="external_markdown_v1",
                factory=_ExternalCustomPluginFormat,
                label="External Markdown Dialog",
                priority=40,
                plugin_id="third_party.markdown",
            )
        ]
    )
    rows_zh = list_dialog_formats(locale="zh_CN")
    assert [row["id"] for row in rows_zh] == [
        "xml_v1",
        "renpy_v1",
        "json_v1",
        "external_markdown_v1",
    ]
    assert rows_zh[-1] == {
        "id": "external_markdown_v1",
        "label": "外部 Markdown 对话格式",
        "builtin": False,
    }
    rows_en = {row["id"]: row for row in list_dialog_formats(locale="en")}
    assert rows_en["external_markdown_v1"]["label"] == "External Markdown Dialog"


def test_discover_builtin_dialog_formats_rejects_duplicates_and_non_subclasses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = tmp_path / "dup_formats_pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "fmt_a.py").write_text(
        "from ai.llm.formats.registry import builtin_dialog_format\n"
        "from sdk.adapters.dialog_format import DialogOutputFormat\n"
        "from ai.llm.formats.xml.parser import XmlTagsStreamParser\n"
        "@builtin_dialog_format(order=10)\n"
        "class FmtA(DialogOutputFormat):\n"
        "    format_id = 'dup_fmt_v1'\n"
        "    def create_stream_parser(self): return XmlTagsStreamParser()\n"
        "    def parse_complete(self, raw): return []\n"
        "    def validate(self, raw): return True\n",
        encoding="utf-8",
    )
    (pkg_dir / "fmt_b.py").write_text(
        "from ai.llm.formats.registry import builtin_dialog_format\n"
        "from sdk.adapters.dialog_format import DialogOutputFormat\n"
        "from ai.llm.formats.xml.parser import XmlTagsStreamParser\n"
        "@builtin_dialog_format(order=20)\n"
        "class FmtB(DialogOutputFormat):\n"
        "    format_id = 'dup_fmt_v1'\n"
        "    def create_stream_parser(self): return XmlTagsStreamParser()\n"
        "    def parse_complete(self, raw): return []\n"
        "    def validate(self, raw): return True\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        pkg = importlib.import_module("dup_formats_pkg")
        with pytest.raises(ValueError, match="Duplicate built-in dialog format id"):
            discover_builtin_dialog_formats(pkg)
    finally:
        for name in [m for m in sys.modules if m == "dup_formats_pkg" or m.startswith("dup_formats_pkg.")]:
            sys.modules.pop(name, None)

    bad_dir = tmp_path / "bad_target_pkg"
    bad_dir.mkdir()
    (bad_dir / "__init__.py").write_text("", encoding="utf-8")
    (bad_dir / "bad.py").write_text(
        "from ai.llm.formats.registry import builtin_dialog_format\n"
        "@builtin_dialog_format()\n"
        "class NotAFormat:\n"
        "    format_id = 'nope'\n",
        encoding="utf-8",
    )
    try:
        bad_pkg = importlib.import_module("bad_target_pkg")
        with pytest.raises(TypeError, match="DialogOutputFormat subclass"):
            discover_builtin_dialog_formats(bad_pkg)
    finally:
        for name in [m for m in sys.modules if m == "bad_target_pkg" or m.startswith("bad_target_pkg.")]:
            sys.modules.pop(name, None)

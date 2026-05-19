from __future__ import annotations

from types import SimpleNamespace

import pytest

from ui.settings_ui.services import chat_template_handlers as qt_templates
from ui.webui import chat_template_handlers as web_templates


pytestmark = pytest.mark.unit


def test_settings_template_save_rejects_path_traversal(tmp_path) -> None:
    ctx = SimpleNamespace(template_dir_path=str(tmp_path))
    outside = tmp_path.parent / f"{tmp_path.name}_outside.txt"

    message, _files = qt_templates.save_template(ctx, "scenario", "system", f"../{outside.stem}")

    assert message.startswith("保存失败")
    assert not outside.exists()


def test_settings_template_load_rejects_absolute_path(tmp_path) -> None:
    ctx = SimpleNamespace(template_dir_path=str(tmp_path))
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    scenario, system, _filename = qt_templates.load_template_from_file(ctx, str(outside))

    assert scenario.startswith("加载失败")
    assert system == ""


def test_web_template_save_rejects_path_traversal(tmp_path) -> None:
    ctx = SimpleNamespace(template_dir_path=str(tmp_path))
    outside = tmp_path.parent / f"{tmp_path.name}_outside.txt"

    message, _files = web_templates.save_template(ctx, "template", f"../{outside.stem}")

    assert message.startswith("保存失败")
    assert not outside.exists()


def test_web_template_load_accepts_single_segment_filename(tmp_path) -> None:
    ctx = SimpleNamespace(template_dir_path=str(tmp_path))
    (tmp_path / "safe.txt").write_text("template", encoding="utf-8")

    template, filename = web_templates.load_template_from_file(ctx, "safe")

    assert template == "template"
    assert filename == "safe.txt"

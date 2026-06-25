from __future__ import annotations

from types import SimpleNamespace

from ui.webui.chat_template_handlers import load_template_from_file, save_template


def _ctx(template_dir):
    return SimpleNamespace(template_dir_path=str(template_dir))


def test_load_template_only_reads_existing_template_catalog_entry(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "safe.txt").write_text("hello", encoding="utf-8")

    template, filename = load_template_from_file(_ctx(template_dir), "safe")

    assert template == "hello"
    assert filename == "safe.txt"


def test_load_template_rejects_traversal_even_when_target_exists(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    template, filename = load_template_from_file(_ctx(template_dir), "../outside.txt")

    assert "加载失败" in template
    assert filename == "../outside.txt"


def test_save_template_rejects_path_segments(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    message, files = save_template(_ctx(template_dir), "body", "../evil")

    assert "保存失败" in message
    assert files == []
    assert not (tmp_path / "evil.txt").exists()


def test_save_template_writes_single_safe_txt_name(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    message, files = save_template(_ctx(template_dir), "body", "story")

    assert message == "保存成功"
    assert files == ["story.txt"]
    assert (template_dir / "story.txt").read_text(encoding="utf-8") == "body"

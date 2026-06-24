import os
import time

from core.plugins.github_bundle_update import mark_frontend_dist_fresh, merge_source_tree_into


def test_merge_source_tree_keeps_frontend_dist_but_skips_local_artifacts(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    (source / "frontend" / "dist" / "web-assets").mkdir(parents=True)
    (source / "frontend" / "dist" / "index.html").write_text("new frontend", encoding="utf-8")
    (source / "frontend" / "dist" / "web-assets" / "app.js").write_text("js", encoding="utf-8")
    (source / "frontend" / "src").mkdir(parents=True)
    (source / "frontend" / "src" / "main.tsx").write_text("source", encoding="utf-8")
    (source / "frontend" / "node_modules" / "pkg").mkdir(parents=True)
    (source / "frontend" / "node_modules" / "pkg" / "index.js").write_text("skip", encoding="utf-8")
    (source / "dist").mkdir()
    (source / "dist" / "root.txt").write_text("skip", encoding="utf-8")
    (source / "build").mkdir()
    (source / "build" / "root.txt").write_text("skip", encoding="utf-8")
    (source / "data").mkdir()
    (source / "data" / "local.yaml").write_text("skip", encoding="utf-8")

    merge_source_tree_into(dest, source, also_skip_top_level=frozenset({"data"}))

    assert (dest / "frontend" / "dist" / "index.html").read_text(encoding="utf-8") == "new frontend"
    assert (dest / "frontend" / "dist" / "web-assets" / "app.js").is_file()
    assert (dest / "frontend" / "src" / "main.tsx").is_file()
    assert not (dest / "frontend" / "node_modules").exists()
    assert not (dest / "dist").exists()
    assert not (dest / "build").exists()
    assert not (dest / "data").exists()


def test_mark_frontend_dist_fresh_updates_index_mtime(tmp_path):
    index_path = tmp_path / "frontend" / "dist" / "index.html"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("built", encoding="utf-8")
    old_time = time.time() - 120
    os.utime(index_path, (old_time, old_time))

    assert mark_frontend_dist_fresh(tmp_path) is True
    assert index_path.stat().st_mtime > old_time

import os
import time

import pytest

from webui_react import _ensure_frontend_dist


def test_existing_stale_dist_is_served_when_build_environment_is_missing(tmp_path, capsys):
    frontend_dir = tmp_path / "frontend"
    source_path = frontend_dir / "src" / "main.tsx"
    index_path = frontend_dir / "dist" / "index.html"
    source_path.parent.mkdir(parents=True)
    index_path.parent.mkdir(parents=True)
    source_path.write_text("source", encoding="utf-8")
    index_path.write_text("built", encoding="utf-8")
    now = time.time()
    os.utime(index_path, (now - 120, now - 120))
    os.utime(source_path, (now, now))

    _ensure_frontend_dist(
        tmp_path,
        frontend_dir / "dist",
        build_if_missing=True,
        build_if_stale=True,
    )

    assert "Serving the existing built frontend" in capsys.readouterr().err


def test_missing_dist_still_fails_without_build_environment(tmp_path):
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()

    with pytest.raises(SystemExit) as exc_info:
        _ensure_frontend_dist(
            tmp_path,
            frontend_dir / "dist",
            build_if_missing=True,
            build_if_stale=True,
        )

    assert "frontend dependencies are not installed" in str(exc_info.value)

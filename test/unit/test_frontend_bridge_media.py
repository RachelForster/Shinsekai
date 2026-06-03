from __future__ import annotations

import pytest

from frontend_bridge_core.media import _media_thumbnail

Image = pytest.importorskip("PIL.Image")


def test_media_thumbnail_generates_cached_small_image(tmp_path):
    source = tmp_path / "data" / "background.png"
    source.parent.mkdir()
    Image.new("RGB", (800, 480), "#336699").save(source)

    thumbnail = _media_thumbnail(source, project_root=tmp_path, size=96)

    assert thumbnail.is_file()
    assert thumbnail.parent == tmp_path / ".cache" / "frontend-media-thumbnails"
    with Image.open(thumbnail) as generated:
        assert max(generated.size) <= 96
        assert generated.format == "PNG"

    assert _media_thumbnail(source, project_root=tmp_path, size=96) == thumbnail

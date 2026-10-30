from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest
from PIL import Image

from tools import remove_bg


@pytest.fixture
def rembg(monkeypatch):
    api = SimpleNamespace(
        new_session=Mock(return_value=object()),
        remove=Mock(
            side_effect=lambda image, **_: Image.new("RGBA", image.size, (1, 2, 3, 128))
        ),
    )
    monkeypatch.setitem(sys.modules, "rembg", api)
    remove_bg._anime_session.cache_clear()
    yield api
    remove_bg._anime_session.cache_clear()


def test_cutout_preserves_size_alpha_and_source_and_reuses_cpu_model(tmp_path, rembg):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 32), "white").save(source)
    for name in ("one", "two"):
        output = tmp_path / f"{name}.png"
        remove_bg.ai_remove_background(source, output)
        with Image.open(output) as image:
            assert image.mode == "RGBA" and image.size == (24, 32)
            assert image.getchannel("A").getextrema() == (128, 128)
    rembg.new_session.assert_called_once_with(
        "isnet-anime", providers=["CPUExecutionProvider"]
    )
    with Image.open(source) as image:
        assert image.mode == "RGB"


def test_failure_is_reported_without_replacing_existing_output(tmp_path, rembg):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 32)).save(source)
    output = tmp_path / "old.png"
    output.write_bytes(b"previous result")
    rembg.remove.side_effect = RuntimeError("inference failed")
    with pytest.raises(RuntimeError, match="inference failed"):
        remove_bg.ai_remove_background(source, output)
    assert output.read_bytes() == b"previous result"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["old.png", "source.png"]


def test_batch_outputs_png_and_counts_failures(tmp_path, rembg):
    for name in ("one.jpg", "two.png"):
        Image.new("RGB", (24, 32)).save(tmp_path / name)
    rembg.remove.side_effect = [Image.new("RGBA", (24, 32)), RuntimeError("failed")]
    output = tmp_path / "output"
    result = remove_bg.batch_remove_background(str(tmp_path), str(output))
    assert "成功处理: 1，失败: 1" in result
    assert (output / "one.png").is_file()
    assert not (output / "one.jpg").exists()

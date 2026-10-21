import json
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image, ImageChops, ImageDraw

from ai.t2i.reference_image import fit_reference_to_canvas, reference_canvas_size
from ai.t2i.t2i_adapter import ComfyUIT2IAdapter


@pytest.mark.parametrize("size", [(300, 400), (400, 300), (300, 300)])
def test_reference_circle_keeps_its_proportions_on_portrait_canvas(tmp_path, size):
    reference = tmp_path / "reference.png"
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    center = (size[0] // 2, size[1] // 2)
    ImageDraw.Draw(image).ellipse(
        (center[0] - 50, center[1] - 50, center[0] + 50, center[1] + 50), fill="red"
    )
    image.save(reference)
    original = reference.read_bytes()
    with fit_reference_to_canvas(reference, 480, 832) as stream, Image.open(
        stream
    ) as fitted:
        assert fitted.size == (480, 832)
        assert fitted.mode == "RGB"
        assert fitted.getpixel((0, 0)) == (255, 255, 255)
        red, green, _ = fitted.split()
        mask = ImageChops.subtract(red, green).point(
            lambda value: 255 if value > 200 else 0
        )
        left, top, right, bottom = mask.getbbox()
        assert abs((right - left) - (bottom - top)) <= 1
    assert reference.read_bytes() == original


@pytest.mark.parametrize("size", [(300, 400), (400, 300), (300, 300)])
def test_canvas_matches_artwork_without_increasing_generation_budget(tmp_path, size):
    reference = tmp_path / "ref.png"
    Image.new("RGB", size).save(reference)
    width, height = reference_canvas_size(reference, 480, 832)
    assert width % 32 == height % 32 == 0
    assert width * height <= 480 * 832
    assert max(width, height) <= 832
    assert abs(width / height / (size[0] / size[1]) - 1) <= 0.02


@pytest.mark.parametrize("other_anchor", [False, True])
def test_h3_upload_receives_a_fitted_png_instead_of_a_stretched_reference(
    tmp_path, monkeypatch, other_anchor
):
    workflow = {
        "1": {"class_type": "Text", "inputs": {"prompt": ""}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "4": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {"width": 480, "height": 832, "first_frame": ["2", 0]},
        },
    }
    if other_anchor:
        workflow["5"] = {"class_type": "LoadImage", "inputs": {"image": "last.png"}}
        workflow["4"]["inputs"]["last_frame"] = ["5", 0]
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    reference = tmp_path / "reference.webp"
    Image.new("RGB", (300, 400), "red").save(reference, lossless=True)
    monkeypatch.setattr(ComfyUIT2IAdapter, "_start_server_process", lambda _: None)
    adapter = ComfyUIT2IAdapter(
        workflow_path=str(path),
        prompt_node_id="1",
        output_node_id="3",
        reference_node_id="2",
    )
    monkeypatch.setattr(adapter, "_wait_for_server_ready", lambda: True)
    monkeypatch.setattr(adapter, "_wait_for_and_get_image", lambda *_: "result.png")
    posted = []

    def post(url, **kwargs):
        if url.endswith("/upload/image"):
            filename, stream = kwargs["files"]["image"]
            assert filename.endswith(".png")
            with Image.open(BytesIO(stream.read())) as uploaded:
                if other_anchor:
                    assert uploaded.size == (480, 832)
                    assert uploaded.getpixel((240, 95)) == (255, 255, 255)
                    assert uploaded.getpixel((240, 96)) == (255, 0, 0)
                    assert uploaded.getpixel((240, 735)) == (255, 0, 0)
                    assert uploaded.getpixel((240, 736)) == (255, 255, 255)
                else:
                    assert uploaded.size == (512, 672)
                    assert uploaded.getpixel((3, 330)) == (255, 255, 255)
                    assert uploaded.getpixel((4, 330)) == (255, 0, 0)
                    assert uploaded.getpixel((507, 330)) == (255, 0, 0)
                    assert uploaded.getpixel((508, 330)) == (255, 255, 255)
            return Mock(json=lambda: {"name": "fitted.png"})
        posted.append(kwargs["json"]["prompt"])
        return Mock(json=lambda: {"prompt_id": "job"})

    monkeypatch.setattr("ai.t2i.t2i_adapter.requests.post", post)
    assert (
        adapter.generate_image("wave", reference_image_path=str(reference))
        == "result.png"
    )
    assert posted[0]["2"]["inputs"]["image"] == "fitted.png"
    assert posted[0]["4"]["inputs"]["width"] == (480 if other_anchor else 512)
    assert posted[0]["4"]["inputs"]["height"] == (832 if other_anchor else 672)
    assert adapter.workflow_template == workflow

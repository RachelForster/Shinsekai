from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image, ImageDraw

from ai.t2i.reference_image import fit_reference_to_canvas
from core.media.chroma_key import (
    SCREEN_COLORS,
    choose_screen_color,
    remove_screen_background,
    screen_prompt,
)


def reference(path, color, *, accent=None):
    image = Image.new("RGBA", (64, 96))
    ImageDraw.Draw(image).rectangle((16, 12, 48, 84), fill=color)
    if accent:
        image.putpixel((30, 20), accent)
    image.save(path)
    return image


def test_selects_one_screen_for_both_anchors_and_preserves_rare_accents(tmp_path):
    first, last = tmp_path / "first.png", tmp_path / "last.png"
    reference(first, "white", accent=(0, 255, 0, 255))
    reference(last, "black", accent=(0, 0, 255, 255))
    original = [path.read_bytes() for path in (first, last)]
    settings = choose_screen_color([first, last])
    assert settings["method"] == "chroma"
    assert tuple(settings["screenColor"]) not in {(0, 255, 0), (0, 0, 255)}
    assert "chroma-key" in screen_prompt(settings)
    assert settings["screenName"] in screen_prompt(settings)
    for path in (first, last):
        with fit_reference_to_canvas(
            path, 64, 96, background=tuple(settings["screenColor"])
        ) as stream:
            with Image.open(stream) as image:
                assert image.getpixel((0, 0)) == tuple(settings["screenColor"])
    assert [path.read_bytes() for path in (first, last)] == original


def test_transparent_rgb_does_not_affect_selection_and_repeat_is_deterministic(
    tmp_path,
):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    image = reference(first, "white")
    data = np.asarray(image).copy()
    data[data[..., 3] == 0, :3] = (255, 0, 255)
    Image.fromarray(data).save(second)
    assert choose_screen_color([first]) == choose_screen_color([second])


def test_opaque_or_colliding_palette_uses_ai_without_recoloring(tmp_path):
    path = tmp_path / "opaque.png"
    Image.new("RGB", (64, 96), "white").save(path)
    assert choose_screen_color([path]) == {"method": "ai", "reason": "opaque-reference"}
    image = reference(path, "white")
    for index, (_, color) in enumerate(SCREEN_COLORS):
        image.putpixel((20 + index, 20), (*color, 255))
    image.save(path)
    assert choose_screen_color([path]) == {
        "method": "ai",
        "reason": "foreground-colors",
    }


def test_dark_clothes_white_hair_and_foreground_color_are_not_punched_out(tmp_path):
    path = tmp_path / "reference.png"
    image = reference(path, "white", accent=(0, 255, 0, 255))
    ImageDraw.Draw(image).rectangle((20, 30, 40, 70), fill="black")
    image.save(path)
    settings = choose_screen_color([path])
    with fit_reference_to_canvas(
        path, 64, 96, background=tuple(settings["screenColor"])
    ) as stream:
        composite = Image.open(stream).copy()
    cutout = remove_screen_background(composite, settings, alpha_matting=False)
    assert cutout.getpixel((0, 0))[3] == 0
    assert cutout.getpixel((18, 15)) == (255, 255, 255, 255)
    assert cutout.getpixel((25, 40)) == (0, 0, 0, 255)
    assert cutout.getpixel((30, 20)) == (0, 255, 0, 255)


def test_matting_refines_screen_mask_without_reclassifying_the_character(
    tmp_path, monkeypatch
):
    path = tmp_path / "reference.png"
    reference(path, "white")
    settings = choose_screen_color([path])
    with fit_reference_to_canvas(
        path, 64, 96, background=tuple(settings["screenColor"])
    ) as stream:
        composite = Image.open(stream).copy()
    from core.media import alpha_matting

    refine = Mock(
        side_effect=lambda image, mask: Image.merge(
            "RGBA", (*image.convert("RGB").split(), mask)
        )
    )
    monkeypatch.setattr(alpha_matting, "refine_alpha_edges", refine)
    cutout = remove_screen_background(composite, settings)
    refine.assert_called_once()
    assert cutout.getpixel((0, 0))[3] == 0
    assert cutout.getpixel((30, 40))[3] == 255
    assert cutout.size == composite.size


def test_calibrates_h3_and_video_codec_screen_tint_without_cutting_white_or_black():
    image = Image.new("RGB", (64, 96), (19, 255, 8))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 12, 48, 84), fill="white")
    draw.rectangle((20, 30, 40, 70), fill="black")
    settings = {
        "screenColor": [0, 255, 0],
        "screenTolerance": 0.2,
        "screenForegroundDistance": 0.8,
    }
    cutout = remove_screen_background(image, settings, alpha_matting=False)
    assert cutout.getpixel((0, 0))[3] == 0
    assert cutout.getpixel((18, 15)) == (255, 255, 255, 255)
    assert cutout.getpixel((25, 40)) == (0, 0, 0, 255)


def test_video_rgb_padding_keeps_alpha_and_prevents_hidden_screen_from_bleeding():
    from core.media.alpha_matting import pad_transparent_rgb

    image = Image.new("RGBA", (32, 32), (0, 255, 0, 0))
    ImageDraw.Draw(image).rectangle((8, 8, 24, 24), fill=(255, 255, 255, 255))
    padded = pad_transparent_rgb(image)
    assert np.array_equal(np.asarray(padded)[..., 3], np.asarray(image)[..., 3])
    assert padded.getpixel((7, 10)) == (255, 255, 255, 0)
    assert padded.getpixel((10, 10)) == (255, 255, 255, 255)


@pytest.mark.parametrize(
    "invalid", [[0, 0, 0], [False, 255, 0], [0, 255], "green", [0, 256, 0]]
)
def test_invalid_screen_metadata_is_rejected(invalid):
    with pytest.raises(ValueError, match="颜色"):
        remove_screen_background(Image.new("RGB", (32, 32)), {"screenColor": invalid})

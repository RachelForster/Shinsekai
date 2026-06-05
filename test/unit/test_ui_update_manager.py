from core.runtime.ui_update_manager import _load_image_rgba_array, format_context_token_estimate


def test_format_context_token_estimate_is_compact():
    text = format_context_token_estimate(
        {
            "system_prompt_tokens": 1200,
            "history_tokens": 34567,
            "tool_definition_tokens": 890,
            "estimated_total_tokens": 36657,
        }
    )

    assert text == "tokens sys 1.2k | hist 34.6k | tools 890 | total 36.7k"


def test_load_image_rgba_array_supports_unicode_paths(tmp_path):
    from PySide6.QtGui import QColor, QImage

    image_format = getattr(getattr(QImage, "Format", QImage), "Format_RGBA8888")
    image = QImage(2, 1, image_format)
    image.setPixelColor(0, 0, QColor(10, 20, 30, 40))
    image.setPixelColor(1, 0, QColor(50, 60, 70, 255))
    image_path = tmp_path / "立绘.png"

    assert image.save(str(image_path))

    array = _load_image_rgba_array(str(image_path))

    assert array is not None
    assert array.shape == (1, 2, 4)
    assert array[0, 0].tolist() == [10, 20, 30, 40]
    assert array[0, 1].tolist() == [50, 60, 70, 255]

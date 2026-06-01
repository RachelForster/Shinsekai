import pytest

from frontend_bridge_core.media_utils import (
    _optional_suffix_check,
    _path_namespace_list,
    _tag_content,
)


def test_optional_suffix_check_accepts_blank_and_matching_suffix():
    assert _optional_suffix_check("", ".png", "图片") == (True, "")
    assert _optional_suffix_check("Sprite01.PNG", ".png", "图片") == (True, "")


def test_optional_suffix_check_reports_mismatched_suffix():
    assert _optional_suffix_check("Sprite01.webp", ".png", "图片") == (
        False,
        "图片: 文件后缀应为 .png",
    )


def test_path_namespace_list_trims_items_and_rejects_empty_input():
    paths = _path_namespace_list([" /tmp/a.png ", "", None, "/tmp/b.png"])

    assert [item.name for item in paths] == ["/tmp/a.png", "/tmp/b.png"]

    with pytest.raises(ValueError, match="paths must be a list"):
        _path_namespace_list("not-a-list")
    with pytest.raises(ValueError, match="at least one path is required"):
        _path_namespace_list(["", None])


def test_tag_content_supports_full_width_and_ascii_separators():
    assert _tag_content("立绘 1： 开心") == "开心"
    assert _tag_content("Sprite 2: angry") == "angry"
    assert _tag_content("no separator") == "no separator"
    assert _tag_content(None) == ""

from frontend_bridge_core.media_utils import _tag_content


def test_tag_content_supports_full_width_and_ascii_separators():
    assert _tag_content("立绘 1： 开心") == "开心"
    assert _tag_content("Sprite 2: angry") == "angry"
    assert _tag_content("no separator") == "no separator"
    assert _tag_content(None) == ""

from plugins.bilibili_clipboard_cleaner.normalizer import trim_bilibili_share_suffix


def test_trim_bilibili_video_url_after_bv_id():
    text = "https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=333.1007"

    assert trim_bilibili_share_suffix(text) == "https://www.bilibili.com/video/BV1xx411c7mD"


def test_trim_keeps_text_before_bv_id():
    text = "分享 https://www.bilibili.com/video/BV1xx411c7mD/?vd_source=abc"

    assert trim_bilibili_share_suffix(text) == "分享 https://www.bilibili.com/video/BV1xx411c7mD"


def test_trim_leaves_non_bilibili_text_unchanged():
    text = "https://example.com/video/BV1xx411c7mD/?spm_id_from=333.1007"

    assert trim_bilibili_share_suffix(text) == text


def test_trim_leaves_bilibili_without_bv_id_unchanged():
    text = "https://www.bilibili.com/"

    assert trim_bilibili_share_suffix(text) == text


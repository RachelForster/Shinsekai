import pytest

from sdk.voice_tags import VOICE_TAG_PATTERN, strip_voice_tags


@pytest.mark.parametrize("source,expected", [
    ("I feel [sad-face] very tired", "I feel very tired"),
    ("[happy]Hello", "Hello"),
    ("你好[大笑]。", "你好。"),
    ("one\n[sad]\ntwo", "one\n\ntwo"),
    ("[not a tag] stays", "[not a tag] stays"),
    ("unchanged", "unchanged"),
])
def test_tag_cleanup_preserves_word_boundaries(source, expected):
    assert strip_voice_tags(source) == expected


def test_detection_uses_the_same_tag_grammar():
    assert VOICE_TAG_PATTERN.findall("[sad-face] [happy_1] [大笑]") == ["sad-face", "happy_1", "大笑"]

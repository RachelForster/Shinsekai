from core.media.effect_bindings import EffectBinding, parse_effect_bindings


def test_parse_effect_bindings_preserves_line_alignment() -> None:
    bindings = parse_effect_bindings(
        "特效 1：吓到\n\nEffect 3: 提示\n",
        ["one.wav", "unused.wav", "three.wav"],
    )

    assert bindings == (
        EffectBinding("吓到", "one.wav"),
        EffectBinding("提示", "three.wav"),
    )


def test_parse_effect_bindings_expands_multiple_keywords() -> None:
    bindings = parse_effect_bindings(
        "晕掉, 晕过去，晕倒,眩晕,晕掉",
        ["faint.wav"],
    )

    assert [binding.keyword for binding in bindings] == [
        "晕掉",
        "晕过去",
        "晕倒",
        "眩晕",
    ]
    assert {binding.path for binding in bindings} == {"faint.wav"}
    assert {binding.source_label for binding in bindings} == {
        "晕掉, 晕过去，晕倒,眩晕,晕掉"
    }


def test_parse_effect_bindings_ignores_unpaired_values() -> None:
    assert parse_effect_bindings("特效 1：\n特效 2：爆炸", ["one.wav"]) == ()
    assert parse_effect_bindings("特效 1：爆炸", []) == ()


def test_resource_bindings_preserve_indices_for_images_and_mixed_colons():
    bindings = parse_effect_bindings(
        "Image 1: first\n\nImage 3: third：detail\n", ["a.png", "b.png", "c.png"]
    )
    assert [(item.keyword, item.path, item.index) for item in bindings] == [
        ("first", "a.png", 0), ("third：detail", "c.png", 2)
    ]

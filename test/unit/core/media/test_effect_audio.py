from core.media.effect_audio import EffectAudioBinding, parse_effect_audio_bindings


def test_parse_effect_audio_bindings_preserves_line_alignment() -> None:
    bindings = parse_effect_audio_bindings(
        "特效 1：吓到\n\nEffect 3: 提示\n",
        ["one.wav", "unused.wav", "three.wav"],
    )

    assert bindings == (
        EffectAudioBinding("吓到", "one.wav"),
        EffectAudioBinding("提示", "three.wav"),
    )


def test_parse_effect_audio_bindings_expands_multiple_keywords() -> None:
    bindings = parse_effect_audio_bindings(
        "晕掉, 晕过去，晕倒,眩晕,晕掉",
        ["faint.wav"],
    )

    assert [binding.keyword for binding in bindings] == [
        "晕掉",
        "晕过去",
        "晕倒",
        "眩晕",
    ]
    assert {binding.audio_path for binding in bindings} == {"faint.wav"}


def test_parse_effect_audio_bindings_ignores_unpaired_values() -> None:
    assert parse_effect_audio_bindings("特效 1：\n特效 2：爆炸", ["one.wav"]) == ()
    assert parse_effect_audio_bindings("特效 1：爆炸", []) == ()

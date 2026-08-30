from types import SimpleNamespace

from application.chat.effects import build_selected_effect_context


def _manager(*effects):
    return SimpleNamespace(config=SimpleNamespace(effect_list=list(effects)))


def _effect(name: str, audio_tags: str, audio_list: list[str]):
    return SimpleNamespace(name=name, audio_tags=audio_tags, audio_list=audio_list)


def test_selected_effect_context_is_empty_without_a_selection():
    context = build_selected_effect_context(_manager(), [])

    assert context.selected_names == ()
    assert context.labels == ()
    assert context.keyword_map == {}
    assert context.prompt_catalog == ""
    assert context.append_prompt_catalog("system") == "system"


def test_selected_effect_context_builds_prompt_and_runtime_map_once(monkeypatch):
    monkeypatch.setattr(
        "application.chat.effects.tr_i18n",
        lambda key: "Available labels" if key == "template_gen.effects_header" else key,
    )
    context = build_selected_effect_context(
        _manager(
            _effect(
                "Ambient",
                "Effect 1：door, open door\nEffect 2：cloth，rustle\n",
                ["door.wav", "cloth.wav"],
            ),
            _effect("Other", "Effect 1：unused\n", ["unused.wav"]),
        ),
        [" ambient ", "missing"],
    )

    assert context.selected_names == ("Ambient",)
    assert context.labels == ("door", "open door", "cloth", "rustle")
    assert context.keyword_map == {
        "door": "door.wav",
        "open door": "door.wav",
        "cloth": "cloth.wav",
        "rustle": "cloth.wav",
    }
    assert context.prompt_catalog == (
        "Available labels\n- door\n- open door\n- cloth\n- rustle"
    )
    assert context.append_prompt_catalog("system rules") == (
        "system rules\n\nAvailable labels\n- door\n- open door\n- cloth\n- rustle"
    )


def test_selected_effect_context_preserves_blank_tag_indexes(monkeypatch):
    monkeypatch.setattr("application.chat.effects.tr_i18n", lambda _key: "Labels")
    context = build_selected_effect_context(
        _manager(
            _effect(
                "Ambient",
                "Effect 1：impact\n\nEffect 3：notice\n",
                ["a1.wav", "a2.wav", "a3.wav"],
            )
        ),
        "Ambient",
    )

    assert context.keyword_map == {
        "impact": "a1.wav",
        "notice": "a3.wav",
    }
    assert "a2.wav" not in context.keyword_map.values()


def test_selected_effect_context_does_not_invent_labels(monkeypatch):
    monkeypatch.setattr("application.chat.effects.tr_i18n", lambda _key: "Labels")
    context = build_selected_effect_context(
        _manager(
            _effect(
                "Custom",
                "Effect 1：typing\nEffect 2：rain\n",
                ["typing.wav", "rain.wav"],
            )
        ),
        ["Custom"],
    )

    assert context.labels == ("typing", "rain")
    assert "打字" not in context.prompt_catalog
    assert "雨天" not in context.prompt_catalog

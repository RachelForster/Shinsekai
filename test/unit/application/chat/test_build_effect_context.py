from types import SimpleNamespace

import pytest

from core.media.effect_image import ImageEffectAsset

from application.chat.build_effect_context import build_effect_context


def _manager(*effects):
    return SimpleNamespace(list_effects=lambda: list(effects))


def _effect(name: str, audio_tags: str, audio_list: list[str], **values):
    return SimpleNamespace(
        name=name,
        audio_tags=audio_tags,
        audio_list=audio_list,
        image_tags=values.get("image_tags", ""),
        image_list=values.get("image_list", []),
        image_audio_list=values.get("image_audio_list", []),
    )


def test_selected_effect_context_is_empty_without_a_selection():
    context = build_effect_context(_manager(), [])

    assert context.selected_names == ()
    assert context.labels == ()
    assert context.keyword_map == {}
    assert context.image_keyword_map == {}


def test_selected_effect_context_builds_labels_and_runtime_maps():
    context = build_effect_context(
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
        "door, open door": "door.wav",
        "cloth": "cloth.wav",
        "rustle": "cloth.wav",
        "cloth，rustle": "cloth.wav",
    }


def test_selected_effect_context_preserves_blank_tag_indexes():
    context = build_effect_context(
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


def test_selected_effect_context_does_not_invent_labels():
    context = build_effect_context(
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
    assert "打字" not in context.labels
    assert "雨天" not in context.labels


def test_selected_effect_context_includes_image_and_bound_audio():
    context = build_effect_context(
        _manager(
            _effect(
                "Items",
                "",
                [],
                image_tags="图片 1：letter, sealed letter\n",
                image_list=["letter.png"],
                image_audio_list=["paper.wav"],
            )
        ),
        ["Items"],
    )

    assert context.labels == ("letter", "sealed letter")
    assert context.image_keyword_map == {
        label: ImageEffectAsset("letter.png", "paper.wav")
        for label in ("letter", "sealed letter", "letter, sealed letter")
    }


@pytest.mark.parametrize("second_audio", [[], [""], ["B.wav"]])
def test_colliding_image_labels_replace_the_entire_resource(second_audio):
    context = build_effect_context(_manager(
        _effect("A", "", [], image_tags="Image 1: Key\n", image_list=["A.png"], image_audio_list=["A.wav"]),
        _effect("B", "", [], image_tags="Image 1: key\n", image_list=["B.png"], image_audio_list=second_audio),
    ), ["A", "B"])
    assert context.image_keyword_map["key"] == ImageEffectAsset("B.png", second_audio[0] if second_audio else "")
    assert context.labels == ("Key",)


def test_image_alias_collision_keeps_audio_aligned_with_its_image_row():
    context = build_effect_context(_manager(_effect(
        "Items", "", [],
        image_tags="Image 1: letter, paper\n\nImage 3: key, paper\n",
        image_list=["letter.png", "unused.png", "key.png"],
        image_audio_list=["letter.wav", "unused.wav", ""],
    )), ["Items"])
    assert context.image_keyword_map["letter"] == ImageEffectAsset("letter.png", "letter.wav")
    assert context.image_keyword_map["paper"] == ImageEffectAsset("key.png", "")
    assert context.image_keyword_map["key, paper"] == ImageEffectAsset("key.png", "")


def test_catalog_capabilities_follow_each_final_alias_binding():
    context = build_effect_context(_manager(_effect(
        "Mixed", "Effect 1: rain, wind\n", ["weather.wav"],
        image_tags="Image 1: wind\n", image_list=["wind.png"],
    )), ["Mixed"])
    catalog = {item.label: item for item in context.catalog}
    assert tuple(catalog) == ("rain", "wind")
    assert catalog["rain"].kind == "audio"
    assert catalog["rain"].modes == ("before", "after", "loop", "stop")
    assert catalog["wind"].kind == "image_audio"
    assert catalog["wind"].modes == ("before", "after")

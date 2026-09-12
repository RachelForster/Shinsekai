from core.messaging.dialog_output import has_valid_dialog_output


VALID_DIALOG = '{"dialog":[{"character_name":"Alice","sprite":"0","speech":"Hi"}]}'


def test_dialog_output_requires_the_entire_content_to_be_valid_json() -> None:
    assert has_valid_dialog_output(VALID_DIALOG) is True
    assert has_valid_dialog_output(f"{VALID_DIALOG}\nextra prose") is False
    assert has_valid_dialog_output(f"{VALID_DIALOG}\n{{broken") is False
    assert has_valid_dialog_output(f"```json\n{VALID_DIALOG}\n```") is False


def test_dialog_output_requires_a_non_empty_complete_dialog_contract() -> None:
    assert has_valid_dialog_output('{"dialog":[]}') is False
    assert has_valid_dialog_output('{"dialog":[{"character_name":"Alice"}]}') is False
    assert (
        has_valid_dialog_output('{"character_name":"Alice","sprite":"0","speech":"Hi"}')
        is False
    )


def test_dialog_output_accepts_vibe_as_the_media_selection_field() -> None:
    assert (
        has_valid_dialog_output(
            '{"dialog":[{"character_name":"Alice","vibe":"quiet smile","speech":"Hi"}]}',
            media_selection_mode="semantic",
        )
        is True
    )
    assert (
        has_valid_dialog_output(
            '{"dialog":[{"character_name":"Alice","speech":"Hi"}]}',
            media_selection_mode="semantic",
        )
        is False
    )


def test_dialog_output_rejects_the_other_modes_media_field() -> None:
    sprite_only = '{"dialog":[{"character_name":"Alice","sprite":"1","speech":"Hi"}]}'
    vibe_only = '{"dialog":[{"character_name":"Alice","vibe":"calm","speech":"Hi"}]}'
    assert has_valid_dialog_output(sprite_only, media_selection_mode="semantic") is False
    assert has_valid_dialog_output(vibe_only, media_selection_mode="indexed") is False


def test_semantic_dialog_allows_fixed_non_media_system_items() -> None:
    content = '{"dialog":[{"character_name":"NARR","speech":"Later..."}]}'
    assert has_valid_dialog_output(content, media_selection_mode="semantic") is True

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

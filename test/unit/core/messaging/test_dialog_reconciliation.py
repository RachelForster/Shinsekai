from __future__ import annotations

from core.messaging.dialog_reconciliation import reconcile_dialog_repair
from sdk.messages import LLMDialogMessage


def _dialog(
    speech: str,
    *,
    name: str = "Alice",
    sprite: str | int | None = "0",
) -> LLMDialogMessage:
    return LLMDialogMessage(character_name=name, speech=speech, sprite=sprite)


def test_exact_repair_appends_nothing() -> None:
    streamed = [_dialog("First"), _dialog("Second", name="Bob", sprite="1")]
    repaired = [_dialog("First"), _dialog("Second", name="Bob", sprite="1")]

    result = reconcile_dialog_repair(streamed, repaired)

    assert result.prefix_matched is True
    assert result.messages_to_append == ()


def test_empty_stream_appends_entire_repair() -> None:
    repaired = [_dialog("First"), _dialog("Second", name="Bob", sprite="1")]

    result = reconcile_dialog_repair([], repaired)

    assert result.prefix_matched is True
    assert result.messages_to_append == tuple(repaired)


def test_prefix_stream_appends_only_repaired_suffix() -> None:
    first = _dialog("First")
    second = _dialog("Second", name="Bob", sprite="1")

    result = reconcile_dialog_repair([first], [first, second])

    assert result.prefix_matched is True
    assert result.messages_to_append == (second,)


def test_intentional_duplicate_in_repaired_suffix_is_preserved() -> None:
    streamed = _dialog("Again")
    repaired_prefix = _dialog("Again")
    repaired_duplicate = _dialog("Again")

    result = reconcile_dialog_repair(
        [streamed],
        [repaired_prefix, repaired_duplicate],
    )

    assert result.prefix_matched is True
    assert result.messages_to_append == (repaired_duplicate,)


def test_non_prefix_repair_appends_nothing() -> None:
    first = _dialog("First")
    missing = _dialog("Missing", name="Bob", sprite="1")
    last = _dialog("Last", name="Carol", sprite="2")

    result = reconcile_dialog_repair(
        [first, last],
        [first, missing, last],
    )

    assert result.prefix_matched is False
    assert result.messages_to_append == ()


def test_numeric_and_string_asset_ids_match() -> None:
    streamed = _dialog("First", sprite=0)
    repaired_prefix = _dialog("First", sprite="0")
    repaired_suffix = _dialog("Second", name="Bob", sprite="1")

    result = reconcile_dialog_repair(
        [streamed],
        [repaired_prefix, repaired_suffix],
    )

    assert result.prefix_matched is True
    assert result.messages_to_append == (repaired_suffix,)


def test_none_and_default_asset_ids_remain_distinct() -> None:
    streamed = _dialog("First", sprite=None)
    repaired = _dialog("First", sprite="-1")

    result = reconcile_dialog_repair([streamed], [repaired])

    assert result.prefix_matched is False
    assert result.messages_to_append == ()

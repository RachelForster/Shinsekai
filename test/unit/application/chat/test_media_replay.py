from __future__ import annotations

import json
from queue import Queue

from application.chat.dialog_media.replay import (
    enqueue_latest_media_replay,
    latest_media_dialogs,
)


class _OpenCC:
    @staticmethod
    def convert(value: str) -> str:
        return value.replace("場", "场")


def _assistant(*dialogs: str) -> dict[str, str]:
    return {
        "role": "assistant",
        "content": json.dumps(
            {"dialog": [json.loads(dialog) for dialog in dialogs]},
            ensure_ascii=False,
        ),
    }


def test_latest_media_dialogs_uses_raw_latest_instruction_for_each_media_kind() -> None:
    messages = [
        _assistant(
            '{"character_name":"SCENE","speech":"","vibe":"day"}',
            '{"character_name":"Alice","speech":"hello","vibe":"calm"}',
            '{"character_name":"bgm","speech":"","vibe":"quiet"}',
        ),
        {"role": "user", "content": "continue"},
        _assistant(
            '{"character_name":"場景","speech":"","vibe":"rain"}',
            '{"character_name":"NARR","speech":"later","vibe":"ignored"}',
            '{"character_name":"Bob","speech":"run","vibe":"afraid"}',
        ),
    ]

    dialogs = latest_media_dialogs(messages, opencc=_OpenCC())

    assert [(dialog.name, dialog.text, dialog.vibe) for dialog in dialogs] == [
        ("bgm", "", "quiet"),
        ("場景", "", "rain"),
        ("Bob", "run", "afraid"),
    ]


def test_enqueue_media_replay_marks_source_dialogs_without_rewriting_them() -> None:
    output = Queue()
    messages = [
        _assistant('{"character_name":"Alice","speech":"original","vibe":"angry"}')
    ]

    has_character = enqueue_latest_media_replay(
        messages,
        dialog_queue=output,
        opencc=_OpenCC(),
    )

    replay = output.get_nowait()
    assert has_character is True
    assert replay.name == "Alice"
    assert replay.text == "original"
    assert replay.vibe == "angry"
    assert replay._presentation_replay is True


def test_dialogue_without_a_sprite_change_keeps_the_previous_stage_sprite() -> None:
    messages = [
        _assistant('{"character_name":"Alice","speech":"hello","sprite":"5"}'),
        _assistant(
            '{"character_name":"Bob","speech":"I can hear you","sprite":"-1"}',
            '{"character_name":"Alice","speech":"still here"}',
        ),
    ]

    dialogs = latest_media_dialogs(messages, opencc=_OpenCC())

    assert [(dialog.name, dialog.asset_id) for dialog in dialogs] == [("Alice", "5")]


def test_player_portrait_alone_does_not_restore_a_stage_sprite() -> None:
    output = Queue()
    messages = [_assistant('{"character_name":"Player","speech":"hello","sprite":"2"}')]

    has_character = enqueue_latest_media_replay(
        messages, dialog_queue=output, opencc=_OpenCC(), player_name="Player",
    )

    assert has_character is False
    assert output.get_nowait().name == "Player"

from __future__ import annotations

import pytest

from core.sprite.chat_history_text import (
    chat_history_to_turns,
    history_payload_to_plain_text,
    history_payload_to_turns,
    parse_assistant_dialog_content,
)


def test_raw_messages_become_dialog_rows_and_skip_system_and_tool() -> None:
    payload = [
        {"role": "system", "content": "secret prompt"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": (
                "```json\n"
                '{"dialog": ['
                '{"character_name": "Alice", "sprite": "1", "speech": "hi"}, '
                '{"character_name": "", "sprite": "-1", "speech": "It starts raining."}'
                "]}\n```"
            ),
        },
        {"role": "assistant", "content": "ordinary assistant reply"},
        {"role": "tool", "name": "search", "content": "private tool result"},
    ]

    assert history_payload_to_turns(payload) == [
        "你: hello",
        "Alice: hi",
        "It starts raining.",
        "assistant: ordinary assistant reply",
    ]
    assert history_payload_to_plain_text(payload) == (
        "你: hello\nAlice: hi\nIt starts raining.\nassistant: ordinary assistant reply"
    )


def test_history_payload_prefers_attachment_display_content_over_internal_blocks() -> None:
    payload = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "internal prompt"},
                {"type": "local_image", "path": "C:/private/scene.png"},
            ],
            "display_content": "Inspect this\n[image: scene.png]",
        }
    ]

    assert history_payload_to_plain_text(payload) == "你: Inspect this\n[image: scene.png]"


def test_structured_turns_keep_speaker_content_and_rendered_text() -> None:
    turns = chat_history_to_turns(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "plain reply"},
        ],
        user_display_name="Player",
    )

    assert turns == [
        {"role": "user", "speaker": "Player", "content": "hello", "text": "Player: hello"},
        {
            "role": "assistant",
            "speaker": "assistant",
            "content": "plain reply",
            "text": "assistant: plain reply",
        },
    ]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"messages": [{"role": "user", "content": "from messages"}]},
            ["你: from messages"],
        ),
        (
            {"history": ["<p><b>你</b>: Tea &amp; cake</p>", "<p><b>Alice</b>: Sure<br>now</p>"]},
            ["你: Tea & cake", "Alice: Sure\nnow"],
        ),
        (
            {
                "historyEntries": [
                    {"id": "one", "role": "assistant", "text": "Alice: ready"},
                    {"id": "two", "role": "system", "text": "Narrator: night falls"},
                ]
            },
            ["Alice: ready", "Narrator: night falls"],
        ),
    ],
)
def test_supported_wrapper_shapes(payload: object, expected: list[str]) -> None:
    assert history_payload_to_turns(payload) == expected


def test_wrapper_prefers_rendered_history_over_other_representations() -> None:
    payload = {
        "history": ["Alice: rendered"],
        "historyEntries": [{"role": "assistant", "text": "Alice: entry"}],
        "messages": [{"role": "assistant", "content": "message"}],
    }

    assert history_payload_to_turns(payload) == ["Alice: rendered"]


def test_branch_export_selects_active_branch_and_prefers_its_history() -> None:
    payload = {
        "version": 1,
        "activeBranchId": "alternate",
        "branches": {
            "main": {
                "id": "main",
                "history": ["Alice: main"],
                "messages": [{"role": "assistant", "content": "main message"}],
            },
            "alternate": {
                "id": "alternate",
                "history": ["Alice: rendered alternate"],
                "messages": [{"role": "assistant", "content": "ignored alternate message"}],
            },
        },
    }

    assert history_payload_to_turns(payload) == ["Alice: rendered alternate"]


def test_branch_list_falls_back_from_empty_history_to_messages() -> None:
    payload = {
        "active": "branch-2",
        "branches": [
            {"id": "main", "history": ["Alice: main"]},
            {
                "id": "branch-2",
                "history": [],
                "messages": [
                    {"role": "user", "content": "continue"},
                    {"role": "assistant", "content": "plain branch reply"},
                ],
            },
        ],
    }

    assert history_payload_to_turns(payload, "Player") == [
        "Player: continue",
        "assistant: plain branch reply",
    ]


def test_assistant_dialog_parser_keeps_fenced_and_repair_behavior() -> None:
    fenced = '```json\n{"dialog": [{"character_name": "Alice", "speech": "hello"}]}\n```'
    malformed = (
        '{"dialog": [{"character_name": "Alice", "speech": "line 1\nline 2"}]}'
    )

    assert parse_assistant_dialog_content(fenced)[0]["speech"] == "hello"
    assert parse_assistant_dialog_content(malformed)[0]["speech"] == "line 1\nline 2"
    assert parse_assistant_dialog_content(
        {"dialog": [{"character_name": "Alice", "speech": "decoded mapping"}]}
    )[0]["speech"] == "decoded mapping"


def test_invalid_payloads_are_empty() -> None:
    assert history_payload_to_turns(None) == []
    assert history_payload_to_turns({"branches": {}}) == []
    assert history_payload_to_turns({"unknown": []}) == []
    assert history_payload_to_plain_text([]) == ""

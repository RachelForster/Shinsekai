"""Hidden control inputs must never resurface as visible chat history when the
runtime rebuilds the React history from persisted LLM messages."""

from frontend_bridge_core.chat import _serialize_history_entries_from_messages


def _assistant(speech: str) -> dict:
    return {
        "role": "assistant",
        "content": f'{{"dialog":[{{"character_name":"Bot","sprite":"1","speech":"{speech}"}}]}}',
    }


def test_serialize_from_messages_skips_hidden_user_turns():
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "hello"},
        _assistant("hi"),
        {"role": "user", "content": "/phone connect", "hidden": True},
        {"role": "user", "content": "bye"},
        _assistant("cya"),
    ]

    entries = _serialize_history_entries_from_messages(messages)

    user_entries = [entry for entry in entries if entry.get("role") == "user"]
    # The hidden "/phone connect" turn is never rendered as player dialogue...
    assert len(user_entries) == 2
    assert user_entries[0]["text"].endswith("hello")
    assert user_entries[1]["text"].endswith("bye")
    # ...and revertUserIndex stays contiguous over visible users only, so it
    # matches the fork/revert user index computed on the runtime side.
    assert [entry["revertUserIndex"] for entry in user_entries] == [0, 1]
    assert all("/phone connect" not in entry["text"] for entry in entries)

import json
from datetime import datetime, timezone

import pytest

from core.sprite.save_slots import (
    count_user_turns,
    get_auto_slot_summary,
    last_user_text,
    list_manual_slots,
    load_slot,
    preview_from_messages,
    save_auto_slot,
    save_slot,
    slot_path,
)


def _messages():
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "[本地时间 2026-05-17 21:00:00]\nこんにちは"},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "dialog": [
                        {
                            "character_name": "Nanami",
                            "speech": "セーブできたよ",
                            "sprite": "1",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        },
    ]


def test_save_slot_roundtrip(tmp_path):
    summary = save_slot(
        "slot_01",
        _messages(),
        background_path="data/bg.png",
        bgm_path="data/bgm.ogg",
        history_file="data/chat_history/main.json",
        save_dir=tmp_path,
        saved_at=datetime(2026, 5, 17, 21, 0, tzinfo=timezone.utc),
    )

    assert summary.exists is True
    assert summary.slot_id == "slot_01"
    assert summary.turn_count == 1
    assert summary.message_count == 3
    assert summary.preview == "Nanami: セーブできたよ"

    payload = load_slot("slot_01", save_dir=tmp_path)
    assert payload["background_path"] == "data/bg.png"
    assert payload["bgm_path"] == "data/bgm.ogg"
    assert payload["messages"][1]["content"].endswith("こんにちは")


def test_list_manual_slots_marks_empty_and_existing(tmp_path):
    save_slot("slot_02", _messages(), save_dir=tmp_path)

    slots = list_manual_slots(save_dir=tmp_path, count=3)

    assert [slot.slot_id for slot in slots] == ["slot_01", "slot_02", "slot_03"]
    assert slots[0].exists is False
    assert slots[1].exists is True
    assert slots[2].exists is False


def test_auto_slot_uses_fixed_path(tmp_path):
    save_auto_slot(_messages(), save_dir=tmp_path)

    auto = get_auto_slot_summary(save_dir=tmp_path)

    assert auto.exists is True
    assert auto.path == slot_path("auto", save_dir=tmp_path)


def test_preview_and_last_user_strip_local_time():
    messages = _messages()[:2]

    assert count_user_turns(messages) == 1
    assert preview_from_messages(messages) == "こんにちは"
    assert last_user_text(messages) == "こんにちは"


def test_invalid_slot_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        save_slot("../bad", _messages(), save_dir=tmp_path)

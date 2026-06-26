from __future__ import annotations

import json
from typing import Any


def strip_orphaned_tool_calls(messages: list[dict[str, Any]]) -> None:
    """Repair stored history by removing orphan tool results and filling missing ones."""
    if not messages:
        return

    orphan_tool_indices: list[int] = []
    for i, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        tool_call_id = message.get("tool_call_id", "")
        ok = False
        for j in range(i - 1, -1, -1):
            role = messages[j].get("role", "")
            if role == "user":
                break
            if role == "assistant" and messages[j].get("tool_calls"):
                if any(call.get("id") == tool_call_id for call in messages[j]["tool_calls"]):
                    ok = True
                break
        if not ok:
            orphan_tool_indices.append(i)

    for index in reversed(orphan_tool_indices):
        del messages[index]

    pending_calls: dict[int, list[dict[str, str]]] = {}
    for i, message in enumerate(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            pending_calls[i] = [
                {"id": call.get("id", ""), "name": call.get("function", {}).get("name", "")}
                for call in message["tool_calls"]
            ]

    inserts: list[tuple[int, dict[str, Any]]] = []
    for assistant_index, calls in pending_calls.items():
        seen_ids: set[str] = set()
        insert_at = assistant_index + 1
        for j in range(assistant_index + 1, len(messages)):
            role = messages[j].get("role", "")
            if role == "user":
                break
            if role == "tool":
                seen_ids.add(messages[j].get("tool_call_id", ""))
                insert_at = j + 1
        for call in calls:
            if call["id"] not in seen_ids:
                inserts.append(
                    (
                        insert_at,
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "name": call["name"],
                            "content": json.dumps({"error": "工具调用失败，请尝试其他方式"}),
                        },
                    )
                )
                insert_at += 1
    for position, message in sorted(inserts, key=lambda item: item[0], reverse=True):
        messages.insert(position, message)


def filter_unpaired_tool_messages_for_request(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return an API-safe copy with only paired assistant tool_calls/tool results."""
    if not messages:
        return messages

    cleaned: list[dict[str, Any]] = []
    changed = False
    i = 0
    while i < len(messages):
        message = messages[i]
        role = message.get("role")

        if role == "tool":
            changed = True
            i += 1
            continue

        tool_calls = message.get("tool_calls")
        if role != "assistant" or not isinstance(tool_calls, list) or not tool_calls:
            cleaned.append(message)
            i += 1
            continue

        valid_calls = [
            call
            for call in tool_calls
            if isinstance(call, dict) and str(call.get("id") or "").strip()
        ]
        expected_id_set = {str(call.get("id") or "") for call in valid_calls}

        tool_block: list[dict[str, Any]] = []
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            tool_block.append(messages[j])
            j += 1

        seen_ids: set[str] = set()
        paired_tools: list[dict[str, Any]] = []
        for tool_message in tool_block:
            tool_call_id = str(tool_message.get("tool_call_id") or "")
            if tool_call_id in expected_id_set and tool_call_id not in seen_ids:
                paired_tools.append(tool_message)
                seen_ids.add(tool_call_id)
            else:
                changed = True

        paired_calls = [call for call in valid_calls if str(call.get("id") or "") in seen_ids]
        if len(paired_calls) != len(tool_calls) or len(paired_tools) != len(tool_block):
            changed = True

        if paired_calls:
            if len(paired_calls) == len(tool_calls):
                cleaned.append(message)
            else:
                filtered_message = dict(message)
                filtered_message["tool_calls"] = paired_calls
                cleaned.append(filtered_message)
            cleaned.extend(paired_tools)
        else:
            filtered_message = dict(message)
            filtered_message.pop("tool_calls", None)
            if str(filtered_message.get("content") or "").strip():
                cleaned.append(filtered_message)
            changed = True

        i = j

    return cleaned if changed else messages


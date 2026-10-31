"""Explicit character and timeline boundaries; display names are never identities."""

from __future__ import annotations

import hashlib
import json


def normalize_scope(value):
    if not isinstance(value, dict):
        raise ValueError("记忆请求必须指定角色与时间线。")
    character = str(value.get("character_id") or "").strip()
    timeline = str(value.get("timeline") or "").strip()
    timeline_id = str(value.get("timeline_id") or "").strip()
    if not character or len(character) > 240 or timeline not in {"daily", "independent"}:
        raise ValueError("记忆角色标识或时间线无效。")
    if timeline == "independent" and (not timeline_id or len(timeline_id) > 240):
        raise ValueError("非日常记忆必须指定独立时间线标识。")
    if timeline == "daily" and timeline_id:
        raise ValueError("日常记忆不能附带独立时间线标识。")
    return {"character_id": character, "timeline": timeline, "timeline_id": timeline_id}


def scope_key(value):
    return "shared-v1:" + hashlib.sha256(json.dumps(normalize_scope(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def event_metadata(value):
    if not isinstance(value, dict):
        raise ValueError("记忆写入必须指定事件来源。")
    result = {k: value[k] for k in ("source_app", "session_id", "event_id", "occurred_at", "evidence", "category", "status", "origin_memory_id", "supersedes_id", "record_kind", "edited_by_user") if k in value}
    for key in ("source_app", "session_id", "event_id"):
        result[key] = str(result.get(key) or "").strip()
        if not result[key] or len(result[key]) > 240:
            raise ValueError(f"缺少有效的记忆来源字段：{key}")
    if len(json.dumps(result, ensure_ascii=False)) > 64000:
        raise ValueError("记忆来源信息过大。")
    return result


def event_key(scope, metadata):
    metadata = event_metadata(metadata)
    return hashlib.sha256(json.dumps([scope_key(scope), *(metadata[k] for k in ("source_app", "session_id", "event_id"))], ensure_ascii=False).encode()).hexdigest()

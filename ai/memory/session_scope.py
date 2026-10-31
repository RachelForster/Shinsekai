"""Persist memory ownership separately from editable prompts and chat messages."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from ai.memory.scope import normalize_scope
from core.chat_history.storage import chat_history_session_dir


def session_scopes(history, characters, root=None):
    root = Path(root or Path.cwd())
    if str(history or '').strip():
        directory = chat_history_session_dir(history).resolve()
        path = directory / 'memory-scope.json'
        directory.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                with path.open('x', encoding='utf-8') as stream:
                    json.dump({'version': 1, 'timeline': 'independent', 'timeline_id': str(uuid4())}, stream)
            except FileExistsError:
                pass
        value = json.loads(path.read_text(encoding='utf-8'))
    else:
        value = {'timeline': 'independent', 'timeline_id': str(uuid4())}
    if value.get('timeline') not in {'daily', 'independent'}:
        raise ValueError('存档记忆归属无效，不能回落到日常记忆。')
    result = {}
    for character in characters:
        identity = str(getattr(character, 'id', '') or '')
        if identity and identity == value.get('player_id'):
            continue
        if not identity:
            raise ValueError('角色缺少稳定 ID，请先更新并保存角色配置。')
        if value['timeline'] == 'daily':
            identity = (value.get('characters') or {}).get(identity, '')
            if not identity:
                raise ValueError('日常存档缺少角色链接身份，不能按名字访问记忆。')
        result[character.name] = normalize_scope({'character_id': identity, 'timeline': value['timeline'], 'timeline_id': value.get('timeline_id', '')})
    return result, value.get('timeline_id') or 'daily'


_runtime_scopes = None
_active_character = ""
_runtime_session = ""


def configure_scopes(scopes, session):
    global _runtime_scopes, _active_character, _runtime_session
    _runtime_scopes = {name.casefold(): normalize_scope(value) for name, value in scopes.items()}
    _active_character = next(iter(_runtime_scopes), "")
    _runtime_session = session


def current_scope(name=None):
    if _runtime_scopes is None:
        return None
    key = str(name or _active_character).casefold()
    if key not in _runtime_scopes:
        raise ValueError("角色不属于当前存档，禁止按名字回落到其他记忆空间。")
    return _runtime_scopes[key]


def tool_metadata():
    from datetime import datetime, timezone
    return {"source_app": "shinsekai", "session_id": _runtime_session, "event_id": str(uuid4()), "occurred_at": datetime.now(timezone.utc).isoformat(), "record_kind": "curated", "category": "manual", "status": "stable"}


def set_active_character(name):
    global _active_character
    _active_character = str(name or "").casefold()

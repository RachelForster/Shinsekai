"""Read existing saves for explicit post sharing; do not expose launch prompts."""
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from application.chat.conversation_library import _record, _details, _history_messages, list_conversations
from application.chat.history.paths import resolve_history_path_for_project
from core.chat_history.storage import chat_history_active_path
from core.chat_history.text import chat_history_to_turns


def post_source(state, body):
    if body.get('action') == 'list':
        return {'conversations': [{k: row[k] for k in ('id', 'title', 'characters', 'updatedAt', 'dokiTimeline')} for row in list_conversations(state)]}
    identity = str(body.get('conversation_id') or '')
    if body.get('action') != 'read' or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('请选择有效存档。')
    try:
        record = _record(state, identity)
    except KeyError as exc:
        raise ValueError('存档已不存在，请刷新列表。') from exc
    path = resolve_history_path_for_project(state, record['historyPath'])
    turns = chat_history_to_turns(_history_messages(chat_history_active_path(path)))
    text = '\n\n'.join(turn['text'] for turn in turns)
    if not text.strip():
        raise ValueError('这个存档还没有可分享的对话。')
    if len(text) > 500000:
        raise ValueError('存档超过 50 万字，请选择较短的存档。')
    details = _details(record)
    return {'id': identity, 'title': details['title'], 'timeline': details['dokiTimeline'], 'count': len(turns), 'text': text}


def post_to_doki(state, body):
    action = body.get('action')
    if action == 'recipients':
        url, payload = 'recipients', None
    elif action == 'request':
        # Force the actual project root and an existing save, never a caller-supplied file path.
        identity = str(body.get('conversation_id') or '')
        if not re.fullmatch(r'[0-9a-f]{64}', identity):
            raise ValueError('请选择有效存档。')
        try:
            _record(state, identity)
        except KeyError as exc:
            raise ValueError('存档已不存在，请刷新列表。') from exc
        url, payload = 'request', {'root': str(Path(state.project_root_dir).resolve()), 'conversation_id': identity, 'recipient_id': str(body.get('recipient_id') or '')}
    else:
        raise ValueError('不支持的分享操作。')
    request = urllib.request.Request('http://127.0.0.1:8000/api/shinsekai/posts/' + url, data=json.dumps(payload).encode() if payload is not None else None, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read(2 * 1024**2))
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read(8192)).get('detail')
        except ValueError:
            message = None
        raise ValueError(message or 'Doki 未能接收分享，请稍后重试。') from exc
    except OSError as exc:
        raise ValueError('请先在本机打开 Doki，再分享存档。') from exc

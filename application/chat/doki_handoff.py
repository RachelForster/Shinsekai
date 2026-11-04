"""Doki handoffs use native templates, history and launch; never a second stage engine."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from uuid import UUID

from core.chat_history.storage import chat_history_session_dir

_lock = threading.RLock()
MANIFEST = 'doki-handoff.json'
RULES = ('用户／玩家 OC 的台词、内心、决定和自主行动由用户本人控制。'
         '不得替用户编写、补全或推断这些内容。只控制其他角色和环境，并承接用户明确输入的内容。'
         '这项约束适用于续档、重新生成与模板切换。用户已经输入的台词是否朗读，沿用明确设置。')
MARKER = '[DOKI_HANDOFF_CONTEXT]'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def handoff_id(value):
    return UUID(str(value)).hex


def directory(state, identity):
    return Path(state.history_dir).resolve() / 'doki' / handoff_id(identity)


def read_manifest(history):
    if not str(history or '').strip():
        return None
    path = chat_history_session_dir(history) / MANIFEST
    if not path.is_file():
        return None
    if path.stat().st_size > 128000:
        raise ValueError('Doki 存档交接信息过大。')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('source') != 'doki' or value.get('version') != 1:
        raise ValueError('Doki 存档交接信息无效，不能放宽玩家控制。')
    return value


def _characters(state, source):
    by_id = {c.id: c for c in state.config_manager.config.characters}
    ids = [row['native_id'] for row in source['characters']]
    player = source.get('player') or {}
    if player:
        ids.append(player['native_id'])
    if len(set(ids)) != len(ids) or any(identity not in by_id for identity in ids):
        raise ValueError('关联角色已不存在、重复或同时被指定为玩家，请重新检查角色链接。')
    return [by_id[identity].name for identity in ids], by_id[player['native_id']].name if player else ''


def validate(source):
    allowed = {'version', 'source', 'handoff_id', 'mode', 'characters', 'player', 'user_name', 'reason', 'offline_prompt', 'player_persona', 'daily_context'}
    if not isinstance(source, dict) or set(source) - allowed or source.get('version') != 1 or source.get('source') != 'doki':
        raise ValueError('不支持的交接协议或字段。')
    handoff_id(source['handoff_id'])
    if source.get('mode') not in {'daily', 'independent'}:
        raise ValueError('请选择日常或非日常模式。')
    actors = source.get('characters')
    if not isinstance(actors, list) or not 1 <= len(actors) <= 8:
        raise ValueError('参与角色数量无效。')
    for row in actors + ([source['player']] if source.get('player') else []):
        if not isinstance(row, dict) or set(row) - {'native_id', 'identity', 'doki_id'} or not row.get('native_id') or not row.get('identity'):
            raise ValueError('交接必须使用已链接的稳定角色身份。')
    for key, limit in [('user_name', 200), ('reason', 2000), ('offline_prompt', 8000), ('player_persona', 2000)]:
        if not isinstance(source.get(key, ''), str) or len(source.get(key, '')) > limit:
            raise ValueError('交接文本过长或格式无效。')
    contexts = source.get('daily_context') or []
    if not isinstance(contexts, list):
        raise ValueError('交接上下文无效。')
    if source['mode'] == 'independent' and any(source.get(key) for key in ['offline_prompt', 'player_persona', 'daily_context']):
        raise ValueError('非日常档禁止带入 Doki 日常记忆、聊天和世界提示词。')
    memories, messages, memory_chars, message_chars = 0, 0, 0, 0
    actor_ids = {row['native_id'] for row in actors}
    for context in contexts:
        if not isinstance(context, dict) or set(context) - {'native_id', 'memories', 'messages'} or context.get('native_id') not in actor_ids:
            raise ValueError('上下文不属于本次参与角色。')
        for kind in ['memories', 'messages']:
            rows = context.get(kind) or []
            if not isinstance(rows, list):
                raise ValueError('上下文列表无效。')
            for row in rows:
                if not isinstance(row, dict) or set(row) - {'id', 'text', 'side', 'at', 'category', 'status'} or not isinstance(row.get('text'), str):
                    raise ValueError('上下文字段无效。')
                if kind == 'memories':
                    memories += 1; memory_chars += len(row['text'])
                else:
                    messages += 1; message_chars += len(row['text'])
    if memories > 8 or memory_chars > 2400 or messages > 12 or message_chars > 3000 or len(canonical(source)) > 48000:
        raise ValueError('交接超过聊天或记忆预算。')


def prepare(state, source):
    validate(source)
    names, player = _characters(state, source)
    target = directory(state, source['handoff_id'])
    fingerprint = hashlib.sha256(canonical(source).encode()).hexdigest()
    with _lock:
        path = target / MANIFEST
        if path.exists():
            stored = read_manifest(target)
            if stored['request_hash'] != fingerprint:
                raise ValueError('同一交接标识不能用不同内容重建。请新建约会或继续原存档。')
            if not (target / 'doki-receipt.json').exists():
                _write_receipt(target, {'status': 'prepared', 'sessionId': ''})
            return status(state, source['handoff_id'])
        target.mkdir(parents=True, exist_ok=True)
        scope = {'version': 1, 'timeline': source['mode'], 'timeline_id': '' if source['mode'] == 'daily' else handoff_id(source['handoff_id'])}
        if source['mode'] == 'daily':
            scope['characters'] = {row['native_id']: row['identity'] for row in source['characters']}
        if source.get('player'):
            scope['player_id'] = source['player']['native_id']
        scope_path = target / 'memory-scope.json'
        if scope_path.exists():
            if json.loads(scope_path.read_text(encoding='utf-8')) != scope:
                raise ValueError('交接存档的记忆归属不一致，请保留原档并新建约会。')
        else:
            with scope_path.open('x', encoding='utf-8') as stream:
                json.dump(scope, stream, ensure_ascii=False)
        stored = {**source, 'request_hash': fingerprint}
        with path.open('x', encoding='utf-8') as stream:
            json.dump(stored, stream, ensure_ascii=False)
        _write_receipt(target, {'status': 'prepared', 'sessionId': ''})
    return status(state, source['handoff_id'])


def _write_receipt(target, value):
    # The receipt contains status and identity only, never stage dialogue.
    path = target / 'doki-receipt.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    merged = {**previous, **value}
    changed = any(previous.get(key) != merged.get(key) for key in ['status', 'sessionId', 'participants'])
    merged['revision'] = previous.get('revision', 0) + int(changed)
    path.write_text(canonical(merged), encoding='utf-8')


def status(state, identity):
    with _lock:
        return _status(state, identity)


def _status(state, identity):
    target = directory(state, identity)
    source = read_manifest(target)
    if source is None:
        raise ValueError('交接存档不存在。')
    receipt = json.loads((target / 'doki-receipt.json').read_text(encoding='utf-8'))
    from application.chat.composition import _chat_process_running
    current = getattr(state, 'chat_session', {}) or {}
    active = _chat_process_running() and bool(current.get('historyPath')) and chat_history_session_dir(current['historyPath']).resolve() == target
    phase = receipt['status']
    if phase in {'ready', 'entered'} and not active:
        phase = 'paused'
    elif phase == 'entered' and time.time() - receipt.get('last_seen', 0) > 20:
        phase = 'unconfirmed'
    return {'handoff_id': handoff_id(identity), 'status': phase, 'mode': source['mode'], 'sessionId': receipt.get('sessionId', ''), 'active': active, 'revision': receipt.get('revision', 0), 'participants': receipt.get('participants') or {row['native_id']: 'present' if receipt['status'] == 'entered' else 'pending' for row in source['characters']}}


def launch(state, identity, *, launcher):
    target = directory(state, identity)
    source = read_manifest(target)
    if source is None:
        raise ValueError('交接存档不存在。')
    from application.chat.composition import _chat_process_running
    with _lock:
        receipt = json.loads((target / 'doki-receipt.json').read_text(encoding='utf-8'))
        if receipt['status'] == 'ended':
            raise ValueError('本次约会已明确结束，原存档保留；请新建另一场约会。')
        if _chat_process_running():
            current = getattr(state, 'chat_session', {}) or {}
            if not current.get('historyPath') or chat_history_session_dir(current['historyPath']).resolve() != target:
                raise ValueError('新世界已有另一场会话。请先保存并关闭，再进入这次约会。')
            if receipt['status'] == 'paused':
                _write_receipt(target, {'status': 'ready'})
            return status(state, identity)
        # A prepared handoff already contains metadata; initialize native storage
        # before the launcher validates its directory, preserving recovery files.
        if not any((target / name).exists() for name in ('active.json', 'active.json.tmp', 'branches.json')):
            with (target / 'active.json').open('x', encoding='utf-8') as stream:
                json.dump([], stream)
        session = configuration(state, identity)['session']
        payload = configured_payload(state, source, session)
        result = launcher(state, payload)
        if result.get('runtimeDependencyError') or result.get('status') == 'error':
            raise RuntimeError('新世界会话尚未启动，请在新世界检查运行组件与模型配置。')
        _write_receipt(target, {'status': 'ready', 'sessionId': result.get('sessionId', '')})
        return status(state, identity)


def acknowledge(state, payload):
    current = getattr(state, 'chat_session', {}) or {}
    history = str(payload.get('historyPath') or '')
    if not history or not current.get('historyPath') or chat_history_session_dir(history).resolve() != chat_history_session_dir(current['historyPath']).resolve() or not payload.get('sessionId') or current.get('sessionId') != payload.get('sessionId'):
        return {'doki': False}
    source = read_manifest(history)
    if source is None:
        return {'doki': False}
    from application.chat.composition import _chat_process_running
    if not _chat_process_running():
        return {'doki': True, 'status': 'paused'}
    with _lock:
        target = chat_history_session_dir(history)
        receipt = json.loads((target / 'doki-receipt.json').read_text(encoding='utf-8'))
        if receipt['status'] in {'paused', 'ended'}:
            return {'doki': True, 'status': receipt['status']}
        participants = {row['native_id']: (receipt.get('participants') or {}).get(row['native_id'], 'present') for row in source['characters']}
        _write_receipt(target, {'status': 'entered', 'sessionId': payload['sessionId'], 'last_seen': time.time(), 'participants': participants})
    return {'doki': True, 'status': 'entered'}



def change_presence(state, payload, *, stopper):
    if set(payload) - {'handoff_id', 'action', 'character_id', 'revision'}:
        raise ValueError('在场事件包含不支持的字段。')
    target = directory(state, payload.get('handoff_id'))
    with _lock:
        source = read_manifest(target)
        if source is None:
            raise ValueError('交接存档不存在。')
        receipt = json.loads((target / 'doki-receipt.json').read_text(encoding='utf-8'))
        if receipt['status'] == 'ended':
            return status(state, source['handoff_id'])
        if payload.get('revision') != receipt.get('revision', 0):
            raise ValueError('现场状态已变化，请刷新后重新操作。')
        action = payload.get('action')
        current = status(state, source['handoff_id'])
        participants = dict(current['participants'])
        if action in {'join', 'leave'}:
            identity = payload.get('character_id')
            if identity not in participants:
                raise ValueError('角色不属于本次约会。')
            if action == 'join' and (not current['active'] or current['status'] != 'entered'):
                raise ValueError('请先恢复并连接现场，再确认角色回到现场。')
            participants[identity] = 'present' if action == 'join' else 'away'
            _write_receipt(target, {'participants': participants})
        elif action == 'pause':
            _write_receipt(target, {'status': 'paused'})
            if current['active']:
                stopper(state, expected_session_id=receipt.get('sessionId'))
        elif action == 'end':
            _write_receipt(target, {'status': 'ended', 'participants': {identity: 'away' for identity in participants}})
            if current['active']:
                stopper(state, expected_session_id=receipt.get('sessionId'))
        else:
            raise ValueError('在场操作无效。')
        return status(state, source['handoff_id'])


def launch_policy(state, body):
    history = str(body.get('historyPath') or '')
    source = read_manifest(history)
    if source is None:
        return body
    receipt = json.loads((chat_history_session_dir(history) / 'doki-receipt.json').read_text(encoding='utf-8'))
    if receipt.get('status') == 'ended':
        raise ValueError('本次约会已明确结束，不能通过普通聊天入口重新启动。')
    names, player = _characters(state, source)
    return {**body, 'characters': names, 'selectedCharacters': names, 'playerCharacter': player, 'allowPlayerDialogue': False, 'resetHistory': False}


def runtime_context(source, config):
    roster = {c.id: c.name for c in config.config.characters}
    participants = [roster.get(row['native_id'], '角色') for row in source['characters']]
    result = [MARKER, RULES, '本档来源为 Doki；上述玩家控制规则优先于模板中相反的代写要求。', '本次实际参与角色：' + '、'.join(participants) + '。模板中其他角色名称不是本次参与者，不能替换这份名单。']
    if source['mode'] == 'daily':
        result += ['【线下相处规则】', source.get('offline_prompt', ''), '【玩家公开人设】', source.get('player_persona', '')]
        names = {c.id: c.name for c in config.config.characters}
        for context in source.get('daily_context') or []:
            name = names.get(context['native_id'], '该角色')
            result += [f'【仅 {name} 已知的历史资料】以下是过去事实与计划，不是现场台词或当前状态；不得自动成为其他角色的知识。', canonical(context)]
    return '\n'.join(result)


def preview_records(state, payload):
    if set(payload) - {'handoff_id', 'offset', 'limit'}:
        raise ValueError('记录预览参数无效。')
    target = directory(state, payload.get('handoff_id'))
    if not target.resolve().is_relative_to(Path(state.history_dir).resolve()):
        raise ValueError('记录不在约会存档目录内。')
    source = read_manifest(target)
    if source is None or source['mode'] != 'independent':
        raise ValueError('只有独立剧情可以通过此入口预览分享。')
    offset, limit = payload.get('offset', 0), payload.get('limit', 40)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 40:
        raise ValueError('记录范围无效。')
    from core.chat_history.storage import chat_history_active_path
    from core.chat_history.text import chat_history_to_turns, parse_assistant_dialog_content
    path = chat_history_active_path(target)
    if not path.is_file():
        raise ValueError('这份独立剧情尚无已保存记录，请先在新世界保存。')
    if not path.resolve().is_relative_to(target.resolve()) or path.stat().st_size > 8 * 1024**2:
        raise ValueError('存档路径或记录大小无效。')
    # Read committed history only. Do not invoke recovery that merges/deletes .tmp files.
    raw = json.loads(path.read_text(encoding='utf-8'))
    turns = []
    for index, message in enumerate(raw if isinstance(raw, list) else [raw]):
        if isinstance(message, dict) and (message.get('role') in {'system', 'tool'} or message.get('tool_calls')):
            continue
        if isinstance(message, dict) and message.get('role') == 'assistant':
            content = message.get('content')
            if (isinstance(content, (dict, list)) or str(content or '').lstrip().startswith(('{', '[', '```'))) and not parse_assistant_dialog_content(content):
                continue
        stamp = str(message.get('created_at') or '')[:100] if isinstance(message, dict) else ''
        for turn in chat_history_to_turns([message], user_display_name=source.get('user_name') or '用户'):
            if turn['role'] in {'system', 'tool'}:
                continue
            text = turn['text']
            identity = hashlib.sha256(canonical([index, len(turns), text, stamp]).encode()).hexdigest()
            turns.append({'id': identity, 'text': text, 'at': stamp, 'speaker': turn['speaker'][:100]})
    rows, budget = [], 6000
    for turn in turns[offset:offset + limit]:
        if not budget:
            break
        text = turn['text'][:min(6000, budget)]
        rows.append({**turn, 'text': text, 'truncated': len(text) < len(turn['text'])})
        budget -= len(text)
    return {'source': 'shinsekai', 'timeline': 'independent', 'title': source.get('reason', '')[:200] or '独立剧情', 'rows': rows, 'offset': offset, 'total': len(turns), 'next_offset': offset + len(rows) if offset + len(rows) < len(turns) else None}


def present_witnesses(history):
    source = read_manifest(history)
    if source is None:
        return None
    try:
        receipt = json.loads((chat_history_session_dir(history) / 'doki-receipt.json').read_text(encoding='utf-8'))
        if receipt['status'] != 'entered':
            return []
        return [row['identity'] if source['mode'] == 'daily' else row['native_id'] for row in source['characters'] if (receipt.get('participants') or {}).get(row['native_id'], 'present') == 'present']
    except (OSError, ValueError, KeyError):
        return []


def install_runtime(llm_manager, config, args):
    source = read_manifest(getattr(args, 'history', ''))
    if source is None:
        return
    args.allow_player_dialogue = False
    player = source.get('player')
    if player:
        args.player_character = next((c.name for c in config.config.characters if c.id == player['native_id']), '')
    from sdk.hooks import PluginHookDispatcher
    dispatcher = getattr(llm_manager, 'hook_dispatcher', None)
    if dispatcher is None:
        dispatcher = PluginHookDispatcher()
        llm_manager.hook_dispatcher = dispatcher
    def before_chat(context):
        context.messages[:] = [m for m in context.messages if not (m.get('role') == 'system' and str(m.get('content') or '').startswith(MARKER))]
        content = runtime_context(source, config)
        witnesses = present_witnesses(args.history) or []
        names = {c.id: c.name for c in config.config.characters}
        present = [names.get(row['native_id'], '角色') for row in source['characters'] if (row['identity'] if source['mode'] == 'daily' else row['native_id']) in witnesses]
        content += '\n【用户确认的当前在场角色】' + '、'.join(present) + '。未在场角色不得作为现场角色继续发言或获得新增亲历；不替用户决定谁加入或离场。'
        context.messages.append({'role': 'system', 'content': content})
    dispatcher.register_before_chat(before_chat, label='doki_player_and_context')


def end_from_native(state, *, expected_session_id=None, stopper):
    """Explicit native End is terminal; ordinary process loss is still resumable."""
    with _lock:
        current = dict(getattr(state, 'chat_session', {}) or {})
        history = current.get('historyPath')
        source = read_manifest(history)
        if source is None:
            return stopper(state, expected_session_id=expected_session_id)
        session_id = current.get('sessionId', '')
        if expected_session_id is not None and expected_session_id != session_id:
            from application.chat.stop_chat import ChatSessionChanged
            raise ChatSessionChanged('The current chat has changed. Confirm the new chat before ending it.')
        result = stopper(state, expected_session_id=session_id)
        target = chat_history_session_dir(history)
        _write_receipt(target, {'status': 'ended', 'participants': {row['native_id']: 'away' for row in source['characters']}})
        return result


def _default_path(state):
    root = Path(getattr(state, 'project_root_dir', Path(state.history_dir).parent))
    return root / 'data/config/doki-daily-default.json'


def _safe_settings(session):
    # Persist only fields supported by the native editor, never Doki memories/history.
    allowed = {'background', 'effectNames', 'enableMobileAccess', 'filenameStub', 'initSpritePath', 'showInitialSprite', 'maxDialogItems', 'maxSpeechChars', 'roomId', 'system', 'templateFileDropdown', 'workflowPath', 'useCg', 'useChoice', 'useCot', 'useEffect', 'useNarration', 'useStat', 'useTranslation', 'voiceLanguage', 'mediaSelectionMode', 'characterPromptMode', 'primaryCharacters', 'readPlayerSpeech'}
    if not isinstance(session, dict) or len(canonical(session)) > 150000:
        raise ValueError('日常线配置无效或过大。')
    return {key: value for key, value in session.items() if key in allowed}


def save_daily_defaults(state, session):
    value = {**_safe_settings(session), 'scenario': str(session.get('scenario') or '')[:8000]}
    # Actor-specific sprite paths are checked again for each actual invitation.
    from application.chat.conversation_library import _write
    with _lock:
        _write(_default_path(state), value)
    return {'session': value}


def configuration(state, identity=None):
    with _lock:
        default_path = _default_path(state)
        defaults = json.loads(default_path.read_text(encoding='utf-8')) if default_path.is_file() else {}
        baseline = {'background': '', 'effectNames': [], 'filenameStub': 'Doki 日常线', 'historyPath': '', 'initSpritePath': '', 'showInitialSprite': True, 'maxDialogItems': 5, 'maxSpeechChars': 20, 'roomId': '', 'scenario': '', 'selectedCharacters': [], 'system': '', 'templateFileDropdown': '', 'workflowPath': '', 'useCg': False, 'useChoice': True, 'useCot': False, 'useEffect': True, 'useNarration': True, 'useStat': True, 'useTranslation': True, 'voiceLanguage': '', 'mediaSelectionMode': 'indexed', 'enableMobileAccess': False, 'playerCharacter': '', 'allowPlayerDialogue': False, 'readPlayerSpeech': False}
        if not identity:
            return {'session': {**baseline, **defaults}}
        target = directory(state, identity)
        source = read_manifest(target)
        if source is None:
            raise ValueError('交接存档不存在。')
        path = target / 'doki-settings.json'
        from_defaults = False
        if path.is_file():
            settings = json.loads(path.read_text(encoding='utf-8'))
        else:
            # An existing native save owns its launch configuration, even after defaults change.
            from application.chat.conversation_library import saved_conversation_launch
            saved = saved_conversation_launch(state, target) if hasattr(state, 'template_dir_path') else None
            if saved:
                settings = saved.get('editorSession') or {
                    'background': saved.get('backgroundName', ''), 'effectNames': saved.get('effectNames', []),
                    'initSpritePath': saved.get('initSpritePath', ''), 'showInitialSprite': saved.get('showInitialSprite', True),
                    'mediaSelectionMode': saved.get('mediaSelectionMode', 'indexed'), 'useCg': bool(saved.get('useCg')),
                    'system': saved.get('system', ''), 'scenario': saved.get('scenario', ''),
                    'templateFileDropdown': saved.get('templateId', ''), 'filenameStub': saved.get('templateName', ''),
                    'workflowPath': saved.get('workflowPath', ''), 'voiceLanguage': saved.get('voiceLanguage', ''),
                }
            elif any((target / name).exists() for name in ('active.json', 'active.json.tmp', 'branches.json')):
                settings = {}
            else:
                settings = defaults if source['mode'] == 'daily' else {}
                from_defaults = source['mode'] == 'daily'
        session = {**baseline, **_safe_settings(settings)}
        names, player = _characters(state, source)
        if not session['system']:
            session['system'], _ = state.template_generator.generate_chat_template(
                names, str(session.get('background') or ''),
                bool(session.get('useEffect', True)), bool(session.get('useCg', False)),
                bool(session.get('useTranslation', True)), bool(session.get('useCot', False)),
                bool(session.get('useChoice', True)), bool(session.get('useNarration', True)),
                bool(session.get('useStat', True)),
                max_speech_chars=max(0, int(session.get('maxSpeechChars') or 0)),
                max_dialog_items=max(0, int(session.get('maxDialogItems') or 0)),
                primary_characters=session.get('primaryCharacters') if session.get('characterPromptMode') == 'compact' else None,
                media_selection_mode=session.get('mediaSelectionMode', 'indexed'),
                player_character=player,
                read_player_speech=bool(session.get('readPlayerSpeech', False)),
                allow_player_dialogue=False,
            )
        sprite = str(session.get('initSpritePath') or '')
        warnings = []
        if sprite:
            actors = [c for c in state.config_manager.config.characters if c.name in names]
            root = Path(getattr(state, 'project_root_dir', Path.cwd()))
            def asset_path(value):
                candidate = Path(str(value))
                return (candidate if candidate.is_absolute() else root / candidate).resolve()
            paths = {asset_path(row.get('path', '') if isinstance(row, dict) else getattr(row, 'path', '')) for actor in actors for row in getattr(actor, 'sprites', [])}
            if asset_path(sprite) not in paths:
                session['initSpritePath'] = ''
                warnings.append('默认初始立绘不属于本次参与角色，请重新选择。')
        session['primaryCharacters'] = [name for name in session.get('primaryCharacters', names) if name in names] or names
        scenario = str(settings.get('scenario') or source.get('reason') or '与用户见面。')
        if from_defaults and settings.get('scenario') and source.get('reason'):
            scenario += '\n\n【本次邀约】' + source['reason']
        session.update(selectedCharacters=names, playerCharacter=player, allowPlayerDialogue=False, scenario=scenario, historyPath=str(target))
        if not path.exists():
            with path.open('x', encoding='utf-8') as stream:
                json.dump({**_safe_settings(session), 'scenario': session['scenario']}, stream, ensure_ascii=False)
        return {'session': session, 'handoff_id': handoff_id(identity), 'mode': source['mode'], 'warnings': warnings, 'ended': json.loads((target / 'doki-receipt.json').read_text(encoding='utf-8')).get('status') == 'ended'}


def configured_payload(state, source, session):
    names, player = _characters(state, source)
    return {'characters': names, 'playerCharacter': player, 'allowPlayerDialogue': False, 'readPlayerSpeech': bool(session.get('readPlayerSpeech')), 'userDisplayName': source.get('user_name') or '用户', 'scenario': session.get('scenario') or source.get('reason') or '与用户见面。', 'system': session.get('system') or '', 'historyPath': str(directory(state, source['handoff_id'])), 'resetHistory': False, 'templateName': 'Doki 日常线' if source['mode'] == 'daily' else 'Doki 独立剧情', 'mediaSelectionMode': session.get('mediaSelectionMode', 'indexed'), 'useCg': bool(session.get('useCg')), 'backgroundName': session.get('background', ''), 'effectNames': session.get('effectNames', []), 'initSpritePath': session.get('initSpritePath', ''), 'showInitialSprite': session.get('showInitialSprite', True), 'workflowPath': session.get('workflowPath', ''), 'voiceLanguage': session.get('voiceLanguage', ''), 'enableMobileAccess': bool(session.get('enableMobileAccess')), 'editorSession': {**session, 'selectedCharacters': names, 'playerCharacter': player, 'allowPlayerDialogue': False, 'readPlayerSpeech': bool(session.get('readPlayerSpeech'))}}


def launch_configured(state, identity, session, *, launcher):
    with _lock:
        target = directory(state, identity)
        source = read_manifest(target)
        if source is None:
            raise ValueError('交接存档不存在。')
        # Validate participants and settings before touching the existing launch snapshot.
        _characters(state, source)
        if status(state, identity)['status'] == 'ended':
            raise ValueError('本次约会已结束，请新建约会。')
        if status(state, identity)['active']:
            raise ValueError('本次约会正在进行，请先暂停再调整启动配置。')
        settings = {**_safe_settings(session), 'scenario': str(session.get('scenario') or source.get('reason') or '')[:8000]}
        from application.chat.conversation_library import _write
        _write(target / 'doki-settings.json', settings)
        result = launch(state, identity, launcher=launcher)
        from application.chat.composition import _chat_snapshot
        return {**result, 'snapshot': _chat_snapshot(state)}

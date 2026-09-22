"""Player identity, portrait-only output, and literal player speech."""

import json
import os
import re

PLAYER_CONTROL_ENV = 'SHINSEKAI_PLAYER_CONTROL'


def player_settings() -> dict:
    raw = os.environ.get(PLAYER_CONTROL_ENV, '')
    try:
        data = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_player(config, names, value) -> str:
    name = str(value or '').strip()
    if not name:
        return ''
    character = config.get_character_by_name(name)
    if character is None or character.name not in names:
        raise ValueError('主控人物必须是已选择的有效角色。')
    return character.name


def player_prompt(config, name: str, read_speech: bool = False) -> str:
    if not name:
        return ''
    character = config.get_character_by_name(name)
    if character is None:
        raise ValueError('主控人物已不存在，请重新选择。')
    speech_contract = ""
    if read_speech:
        voice_language = str(config.config.system_config.voice_language or "ja")
        speech_contract = f'''
必须把 player_speech 放在 JSON 根对象的第一个字段，格式为：{{"player_speech":{{"translate":"用户本轮实际台词的{voice_language}译文"}},"player_portrait":...,"dialog":[...]}}。
player_speech.translate 只翻译用户输入中实际说出的台词；去掉括号、方括号、星号中的动作，以及“心理活动/内心/心想/思考”标记的内容。必须忠实、完整，不得扩写、省略或解释。
player_speech 只用于语音朗读，不属于 dialog，不表示你在代写主控台词。'''
    return f'''\n\n[用户控制的主控人物：{name}]
{character.character_setting}
用户消息是{name}的台词、主动动作及明确表达的心理活动。
禁止为{name}生成任何一句台词或回答，禁止假定用户已经回答或作出关键选择。
允许少量补充旁白、外在动作、语气、眼神和表情，描写其他人物与{name}的互动及其外在结果。
{name}不是你扮演的角色，dialog数组禁止包含{name}的条目，包括空台词条目。
dialog只用于其他人物及现有旁白、选项等系统角色。speech和translate只属于其他人物，禁止生成用户对白。
主控表情在JSON根对象的独立字段player_portrait中输出，并放在dialog之前，便于流式更新，例如：{{"player_portrait":{{"sprite":"01","vibe":"用户表现出的情绪"}},"dialog":[其他角色条目]}}。
player_portrait只允许sprite或vibe，禁止speech、translate、effect、动作、台词或决定。{speech_contract}
主控表情目录：
{character.emotion_tags}
根据用户已输入的回复、动作和明确心理活动选择表情；没有变化时省略player_portrait，不重复输出用户台词。
只有用户本人的发言、动作、明确心理活动，或涉及主控的旁白互动，才可以更新主控表情。
其他角色发言（包括回复主控）不是主控表情更新的依据，不要在每个角色对白之间更新player_portrait。
主控发言只能由用户输入，绝不能代写一句，包括通过旁白引号、间接引语或其他角色之口补写主控回答。
其他人物向主控提出问题、请求或选择后，等待用户回答；可以附加少量旁白、其他角色的即时反应和CHOICE建议，但禁止假定用户已经回答、同意或拒绝来推进后续事件。
CHOICE是尚未执行的用户选项，可以包含备选台词或动作，不等于主控已经说出或执行；只有用户选择后才生效。
不得将角色设定当作用户已经作出的决定。
涉及主控的旁白请明确写出主控姓名；player_portrait对应用户输入或本轮涉及主控的第一段旁白。
旁白继续使用现有旁白角色和格式。'''


def player_speech(text: str) -> str:
    """Parenthesized actions and explicitly marked thoughts never reach TTS."""
    text = re.sub(r'(?m)^\s*(?:心理活动|内心|心想|思考)\s*[:：].*$', '', text)
    text = re.sub(r'【[^】]*】|\[[^\]]*\]|\*[^*]*\*', '', text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r'\([^()]*\)|（[^（）]*）', '', text)
    return text.strip()


def player_runtime_template(
    config, template: str, names: list, name: str, read_speech: bool = False
) -> str:
    """Remove the generated NPC role assignment from saved pre-player templates."""
    if not name:
        return template
    from ai.llm.template_generator import _T
    character = config.get_character_by_name(name)
    separator = _T('name_sep')
    old_names = separator.join(names or [])
    npc_names = separator.join(item for item in (names or []) if item != name)
    if old_names:
        template = template.replace(old_names, npc_names)
    if character is not None:
        blocks = [
            _T('sprites_count', name=name, n=len(character.sprites)) + f'{character.emotion_tags or ""}\n\n',
            _T('profile_for', name=name) + f'{character.character_setting or ""}\n\n',
            _T('brief_for', name=name) + f'{character.character_brief or character.character_setting or ""}\n\n',
        ]
        for block in blocks:
            template = template.replace(block, '')
    return template + player_prompt(config, name, read_speech)

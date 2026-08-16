"""Compose story-mode system prompts from the same dialog contract as free chat."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from ai.llm.template_generator import json_format_reminder, render_dialog_reply_contract
from i18n import current_language, init_i18n
from i18n import tr as tr_i18n


def _T(key: str, **kwargs: Any) -> str:
    init_i18n(current_language())
    return tr_i18n(f"story_scene_prompt.{key}", **kwargs)


def compose_story_system_prompt(
    request: Mapping[str, Any],
    *,
    use_effect: bool = True,
    use_cg: bool = False,
    use_llm_translation: bool = True,
) -> str:
    """Build the six-part story system prompt. Author bible never belongs here."""
    init_i18n(current_language())
    return (
        "\n\n".join(
            part
            for part in (
                compose_story_user_scene_context(request),
                compose_story_chat_system_prompt(
                    request,
                    use_effect=use_effect,
                    use_cg=use_cg,
                    use_llm_translation=use_llm_translation,
                ),
            )
            if part
        ).rstrip()
        + "\n"
    )


def compose_story_user_scene_context(request: Mapping[str, Any]) -> str:
    """Current node and progress only; spliced into the chat user turn."""
    init_i18n(current_language())
    scene = _as_mapping(request.get("scene"))
    return "\n\n".join(
        part
        for part in (
            _section(_T("section_current"), _current_scene_block(scene)),
            _section(_T("section_progress"), _progress_block(scene)),
        )
        if part
    ).strip()


def compose_story_chat_system_prompt(
    request: Mapping[str, Any],
    *,
    use_effect: bool = True,
    use_cg: bool = False,
    use_llm_translation: bool = True,
) -> str:
    """Format, cast, tools, and workflow for the leading chat system message."""
    init_i18n(current_language())
    actor = _as_mapping(request.get("actorContext"))
    tools = _as_sequence(request.get("tools"))
    characters = [
        item for item in _as_sequence(actor.get("characters")) if isinstance(item, Mapping)
    ]
    npc_names = [
        str(item.get("name") or item.get("id") or "").strip()
        for item in characters
        if str(item.get("name") or item.get("id") or "").strip()
        and not item.get("isPlayer")
    ]
    format_block, requirements_block = render_dialog_reply_contract(
        npc_names,
        use_effect=use_effect,
        use_cg=use_cg,
        use_llm_translation=use_llm_translation,
        use_choice=False,
        use_narration=True,
        use_stat=True,
        use_cot=False,
        has_real_background=False,
    )
    return _compose_story_chat_system_sections(
        format_block=format_block.rstrip(),
        requirements_block=requirements_block.rstrip(),
        characters=characters,
        tools=tools,
    )


def _compose_story_chat_system_sections(
    *,
    format_block: str,
    requirements_block: str,
    characters: Sequence[Mapping[str, Any]],
    tools: Sequence[Any],
) -> str:
    sections = [
        _section(_T("section_format"), format_block),
        _section(_T("section_characters"), _characters_block(characters)),
        _section(_T("section_tools"), _tools_block(tools)),
        _section(
            _T("section_workflow"),
            "\n".join(
                [
                    requirements_block,
                    _T("workflow_tools_first"),
                    _T("workflow_then_dialog"),
                    _T("workflow_no_invent"),
                    _T("workflow_no_choice"),
                    _T("workflow_untrusted"),
                    json_format_reminder(),
                ]
            ),
        ),
    ]
    return "\n\n".join(part for part in sections if part).strip()


def compose_story_user_message(request: Mapping[str, Any]) -> str:
    scene = _as_mapping(request.get("scene"))
    user_input = _as_mapping(scene.get("userInput"))
    user_text = str(user_input.get("text") or "").strip()
    parts: list[str] = []
    if str(request.get("mode") or "") == "repair-dialogue":
        error = _as_mapping(request.get("validationError"))
        parts.append(
            _T(
                "repair_header",
                code=str(error.get("code") or ""),
                message=str(error.get("message") or ""),
            )
        )
    if user_text:
        parts.append(f"{_T('player_input_header')}\n{user_text}")
    tool_results = _format_tool_results(_as_sequence(request.get("toolResults")))
    if tool_results:
        parts.append(f"{_T('tool_results_header')}\n{tool_results}")
    return "\n\n".join(parts).strip() or user_text


def _section(title: str, body: str) -> str:
    text = str(body or "").strip()
    if not text:
        return ""
    return f"## {title}\n{text}"


def _current_scene_block(scene: Mapping[str, Any]) -> str:
    lines: list[str] = []
    title = str(scene.get("nodeTitle") or "").strip()
    node_id = str(scene.get("nodeId") or "").strip()
    if title:
        lines.append(_T("node_title", title=title))
    if node_id:
        lines.append(_T("node_id", id=node_id))
    public_context = scene.get("publicContext")
    if public_context not in (None, "", {}, []):
        lines.append(_T("public_context"))
        lines.append(_format_data(public_context))
    intents = scene.get("availableIntentIds")
    if intents not in (None, "", {}, []):
        lines.append(_T("available_intents"))
        lines.append(_format_data(intents))
    return "\n".join(lines).strip()


def _progress_block(scene: Mapping[str, Any]) -> str:
    lines: list[str] = []
    completed = [
        str(item).strip()
        for item in _as_sequence(scene.get("completedNodeIds"))
        if str(item).strip()
    ]
    if completed:
        lines.append(_T("completed_nodes", ids="、".join(completed)))
    canon = [
        str(item).strip()
        for item in _as_sequence(scene.get("canon"))
        if str(item).strip()
    ]
    if canon:
        lines.append(_T("canon"))
        lines.extend(f"- {item}" for item in canon)
    variables = scene.get("visibleVariables")
    if isinstance(variables, Mapping) and variables:
        lines.append(_T("variables"))
        lines.append(_format_data(variables))
    return "\n".join(lines).strip() or _T("no_progress")


def _characters_block(characters: Sequence[Mapping[str, Any]]) -> str:
    if not characters:
        return ""
    chunks: list[str] = []
    for item in characters:
        name = str(item.get("name") or item.get("id") or "").strip()
        if not name:
            continue
        setting = str(item.get("setting") or "").strip()
        block = [f"{name}"]
        if item.get("isPlayer"):
            block.append(_T("player_character"))
            if setting:
                block.append(setting)
            chunks.append("\n".join(block).strip())
            continue
        if setting:
            block.append(setting)
        sprites = [
            sprite
            for sprite in _as_sequence(item.get("sprites"))
            if isinstance(sprite, Mapping)
        ]
        if sprites:
            block.append(_T("sprites_count", name=name, n=len(sprites)))
            for index, sprite in enumerate(sprites, start=1):
                code = str(sprite.get("id") or f"{index:02d}").strip() or f"{index:02d}"
                label = str(sprite.get("label") or "").strip()
                block.append(f"- {code}" + (f"：{label}" if label else ""))
        chunks.append("\n".join(block).strip())
    return "\n\n".join(chunks)


def _tools_block(tools: Sequence[Any]) -> str:
    lines = [_T("tools_intro")]
    for item in tools:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        allowlists = []
        for key, value in item.items():
            if key in {"name", "expectedNodeId", "expectedRevision"}:
                continue
            formatted = _format_data(value)
            if formatted:
                allowlists.append(f"  - {key}: {formatted}")
        entry = f"- {name}"
        if allowlists:
            entry += "\n" + "\n".join(allowlists)
        lines.append(entry)
    return "\n".join(lines).strip()


def _format_tool_results(results: Sequence[Any]) -> str:
    lines: list[str] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip() or "tool"
        ok = bool(item.get("ok"))
        status = _T("tool_ok") if ok else _T("tool_failed")
        detail = str(item.get("error") or item.get("errorCode") or "").strip()
        revision = item.get("revision")
        extra = []
        if revision is not None and str(revision).strip():
            extra.append(f"revision={revision}")
        if detail:
            extra.append(detail)
        suffix = f"（{', '.join(extra)}）" if extra else ""
        lines.append(f"- {name}: {status}{suffix}")
    return "\n".join(lines)


def _format_data(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        if not value:
            return ""
        return json.dumps(_json_safe(value), ensure_ascii=False, indent=2)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return ""
        if all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
            return "、".join(str(item) for item in value if item not in (None, ""))
        return json.dumps(_json_safe(list(value)), ensure_ascii=False, indent=2)
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return value


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()

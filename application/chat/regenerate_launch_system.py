"""Regenerate non-manually-edited conversation launch system prompts after cast rename."""

from __future__ import annotations

from typing import Any


def _launch_opt(
    launch: dict[str, Any], editor: Any, *keys: str, default: Any = None
) -> Any:
    for source in (launch, editor):
        if isinstance(source, dict):
            for key in keys:
                if key in source and source[key] is not None:
                    return source[key]
    return default


def regenerate_launch_system(state: Any, launch: dict[str, Any]) -> bool:
    """Regenerate non-manually-edited conversation launch system prompt after rename."""
    if (
        not isinstance(launch, dict)
        or launch.get("storyPath")
        or launch.get("behaviorId") == "novel_theater"
        or launch.get("novelDocId")
    ):
        return False
    editor = launch.get("editorSession")
    if bool(launch.get("systemManuallyEdited")) or (
        isinstance(editor, dict) and bool(editor.get("systemManuallyEdited"))
    ):
        return False
    template_generator = getattr(state, "template_generator", None)
    config_manager = getattr(state, "config_manager", None)
    if template_generator is None or config_manager is None:
        return False
    has_system = bool(str(launch.get("system") or "").strip()) or (
        isinstance(editor, dict) and bool(str(editor.get("system") or "").strip())
    )
    if not has_system:
        return False

    from ai.llm.template_generator import (
        NoValidCharactersError,
        resolve_chat_template_characters,
    )
    from application.chat.dialog_formats import (
        DEFAULT_DIALOG_FORMAT_ID,
        normalize_output_format,
    )
    from application.chat.player_control import resolve_player
    from config.config_manager import character_name_key

    raw_characters = _launch_opt(
        launch, editor, "characters", "selectedCharacters", default=[]
    )
    if not isinstance(raw_characters, list) or not raw_characters:
        return False
    resolved_names = [
        name
        for name, _char in resolve_chat_template_characters(
            [str(item).strip() for item in raw_characters if str(item).strip()],
            config_manager,
        )
    ]
    if not resolved_names:
        return False

    raw_player = str(_launch_opt(launch, editor, "playerCharacter", default="") or "")
    try:
        player_character = resolve_player(config_manager, resolved_names, raw_player)
    except ValueError:
        player_character = ""

    prompt_mode = str(
        _launch_opt(launch, editor, "characterPromptMode", default="") or ""
    ).strip().lower()
    primary_characters: list[str] | None = None
    if prompt_mode == "compact":
        raw_primary = _launch_opt(launch, editor, "primaryCharacters", default=[])
        candidates = (
            [str(item).strip() for item in raw_primary if str(item).strip()]
            if isinstance(raw_primary, list)
            else []
        )
        resolved_primary = [
            name
            for name, _char in resolve_chat_template_characters(
                candidates, config_manager
            )
        ]
        if player_character and player_character not in resolved_primary:
            resolved_primary.append(player_character)
        selected_keys = {character_name_key(name) for name in resolved_names}
        primary_characters = [
            name
            for name in resolved_primary
            if character_name_key(name) in selected_keys
        ]

    media_mode = str(
        _launch_opt(launch, editor, "mediaSelectionMode", default="indexed") or ""
    ).strip().lower()
    media_selection_mode = "semantic" if media_mode == "semantic" else "indexed"
    background = str(
        _launch_opt(launch, editor, "backgroundName", "background", default="") or ""
    )
    try:
        max_speech_chars = max(
            0, int(_launch_opt(launch, editor, "maxSpeechChars", default=0) or 0)
        )
        max_dialog_items = max(
            0, int(_launch_opt(launch, editor, "maxDialogItems", default=0) or 0)
        )
    except (TypeError, ValueError):
        max_speech_chars, max_dialog_items = 0, 0
    read_player_speech = bool(
        player_character
        and _launch_opt(launch, editor, "readPlayerSpeech", default=False)
    )
    allow_player_dialogue = bool(
        _launch_opt(launch, editor, "allowPlayerDialogue", default=True)
    )

    try:
        content, _result = template_generator.generate_chat_template(
            resolved_names,
            background,
            bool(_launch_opt(launch, editor, "useEffect", default=True)),
            bool(_launch_opt(launch, editor, "useCg", default=False)),
            bool(_launch_opt(launch, editor, "useTranslation", default=True)),
            bool(_launch_opt(launch, editor, "useCot", default=False)),
            bool(_launch_opt(launch, editor, "useChoice", default=True)),
            bool(_launch_opt(launch, editor, "useNarration", default=True)),
            bool(_launch_opt(launch, editor, "useStat", default=True)),
            max_speech_chars=max_speech_chars,
            max_dialog_items=max_dialog_items,
            primary_characters=primary_characters,
            media_selection_mode=media_selection_mode,
            player_character=player_character,
            read_player_speech=read_player_speech,
            allow_player_dialogue=allow_player_dialogue,
            output_format=normalize_output_format(
                _launch_opt(
                    launch,
                    editor,
                    "outputFormat",
                    "output_format",
                    default=DEFAULT_DIALOG_FORMAT_ID,
                )
            ),
        )
    except NoValidCharactersError:
        return False

    launch["system"] = content
    launch.pop("systemStale", None)
    if isinstance(editor, dict) and "system" in editor:
        editor["system"] = content
        editor.pop("systemStale", None)
    return True


__all__ = ["regenerate_launch_system"]

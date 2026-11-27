"""Built-in Ren'Py-style script DSL output format (`renpy_v1`)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import re
import threading
from typing import Protocol, runtime_checkable

from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    CHOICE_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    normalize_character_name,
)
from core.messaging.formats.xml_tags_parser import NEXT_STAGE_OPEN_RE
from sdk.adapters.dialog_format import (
    DialogFormatPromptContext,
    DialogOutfitHint,
    DialogOutfitHintContext,
    DialogOutputFormat,
    DialogPlayerHintContext,
    DialogStreamParser,
    RENPY_DIALOG_FORMAT_ID,
)
from sdk.messages import LLMDialogMessage
from sdk.types import RequirementSpec

from .lexer import format_renpy_speaker, quote_dsl_string
from .parser import RENPY_DIRECTIVE_START_RE, RenpyDslStreamParser


@runtime_checkable
class RenpyPromptProvider(Protocol):
    """Protocol for template-layer prompt renderers bound to `renpy_v1`."""

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None: ...

    def render_requirements(
        self,
        context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None: ...

    def render_outfit_hint(
        self,
        context: DialogOutfitHintContext,
    ) -> DialogOutfitHint | None: ...

    def render_player_hint(
        self,
        context: DialogPlayerHintContext,
    ) -> str | None: ...

    def render_format_reminder(self, *, locale: str) -> str | None: ...

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None: ...


_PROMPT_PROVIDER_LOCK = threading.RLock()
_DEFAULT_PROMPT_PROVIDER: RenpyPromptProvider | None = None


def set_default_renpy_prompt_provider(
    provider: RenpyPromptProvider | None,
) -> None:
    """Register or clear the process-wide fallback prompt provider for `renpy_v1`."""
    global _DEFAULT_PROMPT_PROVIDER
    with _PROMPT_PROVIDER_LOCK:
        _DEFAULT_PROMPT_PROVIDER = provider


def get_default_renpy_prompt_provider() -> RenpyPromptProvider | None:
    """Return the active process-wide prompt provider for `renpy_v1`, if set."""
    with _PROMPT_PROVIDER_LOCK:
        return _DEFAULT_PROMPT_PROVIDER

_QUOTED_SPEAKER_LINE_RE = re.compile(
    r'^(?:"[^"\n]+"|\'[^\'\n]+\'|[^\s\[\]{}<>:"\'][^\n\[\]{}<>:]*)\s*(?:\[[^\]]*\]|\bat\s+[a-zA-Z0-9_-]+\s+)?\s*["\']',
    re.MULTILINE,
)


def _format_bracket_attrs(pairs: list[tuple[str, str | None]]) -> str:
    rendered = [f"{key}={quote_dsl_string(val)}" for key, val in pairs if val is not None and val != ""]
    return f" [{', '.join(rendered)}]" if rendered else ""


def _serialize_cot(speech: str) -> str:
    single = " ".join(str(speech or "").splitlines()).strip()
    return f"cot: {single}"


def _serialize_scene_or_bgm(item: LLMDialogMessage, *, is_scene: bool) -> str:
    cmd = "scene" if is_scene else "play music"
    asset_str = "" if item.asset_id is None else str(item.asset_id).strip()
    vibe = str(item.vibe or "").strip()
    parts = [cmd]
    if asset_str and asset_str != "-1":
        parts.append(asset_str)
    elif vibe:
        parts.append(f"vibe={quote_dsl_string(vibe)}")
    else:
        parts.append("-1")
    extra_pairs: list[tuple[str, str | None]] = [("effect", item.effect)]
    if asset_str not in ("", "-1") and vibe:
        extra_pairs.insert(0, ("vibe", vibe))
    bracket = _format_bracket_attrs(extra_pairs)
    if bracket:
        parts.append(bracket.strip())
    if is_scene and item.transition:
        parts.append(f"with {item.transition}")
    return " ".join(parts)


class RenpyDslDialogFormat(DialogOutputFormat):
    """Streaming Ren'Py-like script DSL output format (`renpy_v1`)."""

    format_id = RENPY_DIALOG_FORMAT_ID
    label = "Ren'Py Script DSL"
    api_response_format = {"type": "text"}

    def __init__(
        self,
        *,
        prompt_provider: RenpyPromptProvider | None = None,
    ) -> None:
        self._prompt_provider = prompt_provider

    def _resolve_prompt_provider(self) -> RenpyPromptProvider | None:
        return (
            self._prompt_provider
            if self._prompt_provider is not None
            else get_default_renpy_prompt_provider()
        )

    def create_stream_parser(self) -> DialogStreamParser:
        return RenpyDslStreamParser()

    def parse_complete(self, raw: str) -> list[LLMDialogMessage]:
        parser = RenpyDslStreamParser()
        messages = list(parser.feed(str(raw or "")))
        messages.extend(parser.flush())
        return messages

    def validate(
        self,
        raw: str,
        *,
        media_selection_mode: str = "indexed",
        speaker_requires_media: Callable[[str], bool] | None = None,
    ) -> bool:
        if not isinstance(raw, str) or not raw.strip():
            return False
        parser = RenpyDslStreamParser()
        messages = list(parser.feed(raw))
        messages.extend(parser.flush())
        if parser.has_errors or not messages or parser.unparsed_remainder:
            return False

        semantic = str(media_selection_mode or "").strip().lower() == "semantic"
        for msg in messages:
            raw_speaker = str(msg.name or "").strip()
            norm = normalize_character_name(raw_speaker)
            if not norm:
                return False
            if norm in (SCENE_ALIASES | BGM_ALIASES):
                if semantic:
                    if not str(msg.vibe or "").strip():
                        return False
                elif (
                    "asset_id" not in msg.model_fields_set
                    or str(msg.asset_id or "").strip() in ("", "-1")
                ):
                    return False
                continue
            if speaker_requires_media is not None and norm not in (
                COT_ALIASES | NARR_ALIASES | CHOICE_ALIASES | STAT_ALIASES | CG_ALIASES | SCENE_ALIASES | BGM_ALIASES
            ):
                eff = str(msg.effect or "").strip().upper()
                if eff == "LEAVE" and not (msg.text or "").strip():
                    continue
                if speaker_requires_media(raw_speaker):
                    if semantic:
                        if not str(msg.vibe or "").strip():
                            return False
                    elif "asset_id" not in msg.model_fields_set or not str(msg.asset_id or "").strip():
                        return False
        return True

    def can_parse(self, raw: str) -> bool:
        text = str(raw or "").strip()
        if not text:
            return False
        lines = text.splitlines()
        if lines and re.match(r"^```[a-zA-Z0-9_-]*\s*$", lines[0].strip()):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        unwrapped = "\n".join(lines).strip()
        if not unwrapped or unwrapped[0] in "{[":
            return False
        if NEXT_STAGE_OPEN_RE.search(unwrapped):
            return False
        if not (
            RENPY_DIRECTIVE_START_RE.search(unwrapped)
            or _QUOTED_SPEAKER_LINE_RE.search(unwrapped)
        ):
            return False
        return bool(self.parse_complete(text))

    def serialize(self, items: Sequence[LLMDialogMessage]) -> str | None:
        lines: list[str] = []
        for item in items:
            norm = normalize_character_name(item.name)
            speech = item.text or ""
            tr_suffix = f" | tr {quote_dsl_string(item.translate)}" if item.translate else ""
            if norm in COT_ALIASES:
                lines.append(_serialize_cot(speech))
            elif norm in SCENE_ALIASES:
                lines.append(_serialize_scene_or_bgm(item, is_scene=True))
            elif norm in BGM_ALIASES:
                lines.append(_serialize_scene_or_bgm(item, is_scene=False))
            elif norm in CG_ALIASES:
                asset_str = None if item.asset_id in (None, "", "-1") else str(item.asset_id)
                attrs = _format_bracket_attrs([("sprite", asset_str), ("vibe", item.vibe), ("effect", item.effect)])
                lines.append(f"cg{attrs} {quote_dsl_string(speech)}" if speech else f"cg{attrs}".strip())
            elif norm in NARR_ALIASES:
                attrs = _format_bracket_attrs([("effect", item.effect)])
                lines.append(f"narr{attrs} {quote_dsl_string(speech)}{tr_suffix}")
            elif norm in STAT_ALIASES:
                lines.append(f"stat {quote_dsl_string(speech)}")
            elif norm in CHOICE_ALIASES:
                opts = [part.strip() for part in speech.split("/") if part.strip()]
                if opts:
                    joined = " | ".join(quote_dsl_string(opt) for opt in opts)
                    lines.append(f"menu: {joined}")
                else:
                    lines.append(f"menu: {quote_dsl_string(speech)}")
            else:
                asset_str = "" if item.asset_id is None else str(item.asset_id).strip()
                eff_upper = str(item.effect or "").strip().upper()
                if (eff_upper == "LEAVE" or asset_str.upper() == "LEAVE") and not speech:
                    lines.append(f"hide {format_renpy_speaker(item.name)}")
                else:
                    attrs = _format_bracket_attrs([
                        ("sprite", asset_str or "-1"),
                        ("vibe", item.vibe),
                        ("outfit", item.outfit),
                        ("motion", item.motion),
                        ("effect", item.effect),
                    ])
                    lines.append(f"{format_renpy_speaker(item.name)}{attrs} {quote_dsl_string(speech)}{tr_suffix}")
        return "\n".join(lines)

    def render_schema_hint(
        self,
        *,
        media_field: str,
        translate_required: bool,
        locale: str,
        prompt_context: DialogFormatPromptContext | None = None,
    ) -> str | None:
        provider = self._resolve_prompt_provider()
        if provider is None:
            return None
        return provider.render_schema_hint(
            media_field=media_field,
            translate_required=translate_required,
            locale=locale,
            prompt_context=prompt_context,
        )

    def render_requirements(
        self,
        prompt_context: DialogFormatPromptContext,
    ) -> Sequence[RequirementSpec] | None:
        provider = self._resolve_prompt_provider()
        if provider is None:
            return None
        return provider.render_requirements(prompt_context)

    def render_outfit_hint(
        self,
        context: DialogOutfitHintContext,
    ) -> DialogOutfitHint | None:
        provider = self._resolve_prompt_provider()
        if provider is None:
            return None
        return provider.render_outfit_hint(context)

    def render_player_hint(
        self,
        context: DialogPlayerHintContext,
    ) -> str | None:
        provider = self._resolve_prompt_provider()
        if provider is None:
            return None
        return provider.render_player_hint(context)

    def render_format_reminder(self, *, locale: str) -> str | None:
        provider = self._resolve_prompt_provider()
        if provider is None:
            return None
        return provider.render_format_reminder(locale=locale)

    def render_repair_prompt(
        self,
        *,
        media_field: str,
        retry: bool,
        locale: str,
        allow_unbound_speakers: bool = False,
        bound_speakers: Sequence[str] = (),
    ) -> str | None:
        provider = self._resolve_prompt_provider()
        if provider is None:
            return None
        return provider.render_repair_prompt(
            media_field=media_field,
            retry=retry,
            locale=locale,
            allow_unbound_speakers=allow_unbound_speakers,
            bound_speakers=bound_speakers,
        )

"""Shared plain-dialogue to dual-granularity long-term-memory extraction logic."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
import json
import logging
import re
from typing import Any

from ai.llm.template.core import TemplateContext
from ai.llm.template.extraction import (
    MEMORY_SIMPLE_EXTRACTION_SPEC,
    MEMORY_STRUCTURED_EXTRACTION_SPEC,
    MemorySimpleExtractionContext,
    MemoryStructuredExtractionContext,
)
from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.memory.chunking import DEFAULT_DIALOGUE_CHUNK_TOKENS, chunk_plain_dialogue
from ai.memory.temporal import resolve_event_timestamp
from ai.memory.token_estimator import estimate_message_tokens
from core.chat_history.text import history_payload_to_plain_text
from sdk.adapters.memory import (
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    ExtractionWindow,
    MemoryDraft,
)

logger = logging.getLogger(__name__)

EXPECTED_OUTPUT_TOKENS_PER_CHUNK = 1_024
MAX_MEMORIES_PER_CHUNK = 8
MAX_MEMORY_CHARS = 800
MAX_GIST_CHARS = 80

_DIALOGUE_KINDS = frozenset({"profile", "episodic", "promise"})
_SELF_NAMES = frozenset({"user", "__self__", "你", "自设", "player", "human"})


def clean_text(value: Any, *, max_chars: int | None = None) -> str:
    text = str(value or "").strip()
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def dialogue_memory_kind(value: Any) -> str:
    """Dialogue can record facts and promises, never configure character canon."""
    kind = clean_text(value, max_chars=24).lower()
    return kind if kind in _DIALOGUE_KINDS else "episodic"


def derive_fallback_gist(detail: str, *, max_chars: int = MAX_GIST_CHARS) -> str:
    """Derive a concise impression gist when the LLM omits an explicit `gist` field."""
    cleaned = clean_text(detail, max_chars=MAX_MEMORY_CHARS)
    if not cleaned:
        return ""
    # Strip parenthetical exact details for a softer high-level impression if long
    simplified = re.sub(r"[（(][^）)]{1,40}[）)]", "", cleaned).strip() or cleaned
    if len(simplified) <= max_chars:
        return simplified
    first_clause = re.split(r"[。！？!?；;\n]", simplified, maxsplit=1)[0].strip()
    if 6 <= len(first_clause) <= max_chars:
        return first_clause
    return simplified[:max_chars].rstrip("，、, ") + "…"


def extract_response_text(response: Any) -> str:
    if response is None:
        return ""
    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            return str(getattr(message, "content", "") or "")
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, list) and content:
                return str(getattr(content[0], "text", "") or content[0])
            return str(content or "")
        if hasattr(response, "text"):
            return str(response.text or "")
    except Exception:
        logger.exception("failed to extract memory summary response")
    return str(response)


def parse_json_payload(text: str) -> Any:
    raw = clean_text(text, max_chars=200_000)
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def build_extraction_prompt(
    dialogue: str,
    default_character_name: str,
    *,
    locale: LocaleInput = None,
) -> str:
    name = clean_text(default_character_name, max_chars=120) or "user"
    active_locale = resolve_dynamic_locale(locale)
    return MEMORY_SIMPLE_EXTRACTION_SPEC.render_user(
        MemorySimpleExtractionContext(
            dialogue=clean_text(dialogue),
            default_character_name=name,
            locale=active_locale,
        )
    )


def build_extraction_messages(
    dialogue: str,
    default_character_name: str,
    *,
    locale: LocaleInput = None,
) -> list[dict[str, str]]:
    active_locale = resolve_dynamic_locale(locale)
    return [
        {
            "role": "system",
            "content": MEMORY_SIMPLE_EXTRACTION_SPEC.render_system(
                TemplateContext(locale=active_locale)
            ),
        },
        {
            "role": "user",
            "content": build_extraction_prompt(
                dialogue,
                default_character_name,
                locale=active_locale,
            ),
        },
    ]


def build_structured_extraction_prompt(
    dialogue: str,
    *,
    character_names: Sequence[str],
    now_iso: str,
    locale: LocaleInput = None,
) -> str:
    cleaned_chars = tuple(
        clean_text(c, max_chars=120)
        for c in character_names
        if clean_text(c, max_chars=120)
    )
    anchor = clean_text(now_iso, max_chars=64) or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    active_locale = resolve_dynamic_locale(locale)
    return MEMORY_STRUCTURED_EXTRACTION_SPEC.render_user(
        MemoryStructuredExtractionContext(
            dialogue=clean_text(dialogue),
            character_names=cleaned_chars,
            now_iso=anchor,
            locale=active_locale,
        )
    )


def build_structured_extraction_messages(
    dialogue: str,
    *,
    character_names: Sequence[str],
    now_iso: str,
    locale: LocaleInput = None,
) -> list[dict[str, str]]:
    active_locale = resolve_dynamic_locale(locale)
    return [
        {
            "role": "system",
            "content": MEMORY_STRUCTURED_EXTRACTION_SPEC.render_system(
                TemplateContext(locale=active_locale)
            ),
        },
        {
            "role": "user",
            "content": build_structured_extraction_prompt(
                dialogue,
                character_names=character_names,
                now_iso=now_iso,
                locale=active_locale,
            ),
        },
    ]


def estimate_extraction_input_tokens(
    dialogue: str,
    default_character_name: str,
    *,
    locale: LocaleInput = None,
) -> int:
    return estimate_message_tokens(
        build_extraction_messages(dialogue, default_character_name, locale=locale)
    )


def parse_extracted_memories(
    response: Any,
    *,
    default_character_name: str,
    force_character_name: str | None = None,
) -> list[dict[str, Any]]:
    parsed = parse_json_payload(extract_response_text(response))
    if isinstance(parsed, dict):
        parsed = parsed.get("memories") or parsed.get("items") or []
    if not isinstance(parsed, list):
        return []

    fallback_name = clean_text(default_character_name, max_chars=120) or "user"
    forced_name = clean_text(force_character_name, max_chars=120)
    out: list[dict[str, Any]] = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        memory = clean_text(
            row.get("memory") or row.get("detail") or row.get("content"),
            max_chars=MAX_MEMORY_CHARS,
        )
        if not memory:
            continue
        try:
            confidence = float(row.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        character_name = forced_name or clean_text(
            row.get("character_name") or row.get("characterName"),
            max_chars=120,
        ) or fallback_name
        out.append(
            {
                "character_name": character_name,
                "memory": memory,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return out[:MAX_MEMORIES_PER_CHUNK]


def _normalize_string_tuple(raw: Any, *, max_items: int = 8, max_chars: int = 60) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    items: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        val = clean_text(entry, max_chars=max_chars)
        if not val:
            continue
        key = val.casefold()
        if key not in seen:
            seen.add(key)
            items.append(val)
        if len(items) >= max_items:
            break
    return tuple(items)


def _self_owner_names(self_persona_name: str = "") -> frozenset[str]:
    cleaned = clean_text(self_persona_name, max_chars=120)
    if cleaned:
        return _SELF_NAMES | {cleaned.casefold()}
    return _SELF_NAMES


def _resolve_attributed_owner(
    raw_character_name: str,
    *,
    allowed_characters: Sequence[str],
    default_character: str,
    self_persona_name: str = "",
) -> tuple[str, str]:
    self_names = _self_owner_names(self_persona_name)
    cleaned = clean_text(raw_character_name, max_chars=120)
    if cleaned.casefold() in self_names:
        return (SCOPE_SELF_PUBLIC, "__self__")
    if not cleaned:
        if default_character.casefold() in self_names:
            return (SCOPE_SELF_PUBLIC, "__self__")
        return (SCOPE_CHAR_CROSS_SAVE, default_character)

    if allowed_characters:
        by_lower = {c.casefold(): c for c in allowed_characters if c}
        matched = by_lower.get(cleaned.casefold())
        if matched is not None:
            return (SCOPE_CHAR_CROSS_SAVE, matched)
        # Guard against hallucinated character names in multi-character or single-character scenes
        if default_character and default_character.casefold() not in self_names:
            return (SCOPE_CHAR_CROSS_SAVE, default_character)
    return (SCOPE_CHAR_CROSS_SAVE, cleaned)


def parse_memory_drafts(
    response: Any,
    *,
    character_names: Sequence[str],
    now_iso: str = "",
    session_id: str = "",
    turn_seq: int | None = None,
    self_persona_name: str = "",
) -> list[MemoryDraft]:
    """Parse structured or legacy LLM JSON output into deduplicated MemoryDraft objects."""
    parsed = parse_json_payload(extract_response_text(response))
    if isinstance(parsed, dict):
        parsed = parsed.get("memories") or parsed.get("items") or []
    if not isinstance(parsed, list):
        return []

    self_names = _self_owner_names(self_persona_name)
    allowed_chars = tuple(
        clean_text(c, max_chars=120)
        for c in character_names
        if clean_text(c, max_chars=120) and clean_text(c, max_chars=120).casefold() not in self_names
    )
    default_char = allowed_chars[0] if allowed_chars else "user"
    drafts: list[MemoryDraft] = []

    for row in parsed:
        if not isinstance(row, dict):
            continue
        detail = clean_text(
            row.get("detail") or row.get("memory") or row.get("content"),
            max_chars=MAX_MEMORY_CHARS,
        )
        if not detail:
            continue
        raw_gist = clean_text(row.get("gist") or row.get("summary"), max_chars=MAX_GIST_CHARS)
        gist = raw_gist or derive_fallback_gist(detail)

        kind = dialogue_memory_kind(row.get("kind"))
        slot_key = clean_text(row.get("slot_key") or row.get("slotKey"), max_chars=120)
        topics = _normalize_string_tuple(row.get("topics") or row.get("topic_tags"), max_items=6)
        entities = _normalize_string_tuple(row.get("entities"), max_items=8)

        raw_imp = row.get("importance")
        if raw_imp is None:
            raw_imp = row.get("confidence", 0.5)
        try:
            importance = max(0.0, min(1.0, float(raw_imp)))
        except (TypeError, ValueError):
            importance = 0.5

        raw_event_time = row.get("event_time") or row.get("event_at") or row.get("eventTime")
        event_at = (
            resolve_event_timestamp(raw_event_time, anchor_iso=now_iso)
            if raw_event_time not in {None, "", "null", "None"}
            else None
        )

        raw_speaker = clean_text(
            row.get("character_name") or row.get("characterName") or row.get("owner_id"),
            max_chars=120,
        )
        scope, owner_id = _resolve_attributed_owner(
            raw_speaker,
            allowed_characters=allowed_chars,
            default_character=default_char,
            self_persona_name=self_persona_name,
        )

        drafts.append(
            MemoryDraft(
                owner_id=owner_id,
                detail_text=detail,
                gist_text=gist,
                scope=scope,
                slot_key=slot_key,
                kind=kind,
                topic_tags=topics,
                entities=entities,
                importance=importance,
                pinned=False,
                event_at=event_at,
                source_session_id=clean_text(session_id, max_chars=128),
                source_turn_seq=None if turn_seq is None else int(turn_seq),
            )
        )
        if len(drafts) >= MAX_MEMORIES_PER_CHUNK:
            break
    return drafts


def deduplicate_memories(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        character_name = clean_text(row.get("character_name") or row.get("characterName")) or "user"
        memory = clean_text(row.get("memory") or row.get("content"))
        if not memory:
            continue
        normalized_memory = " ".join(memory.casefold().split())
        key = f"{character_name.casefold()}\n{normalized_memory}"
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append({**row, "character_name": character_name, "memory": memory})
    return unique, duplicates


def deduplicate_drafts(drafts: Iterable[MemoryDraft]) -> list[MemoryDraft]:
    unique: list[MemoryDraft] = []
    seen_text: set[str] = set()
    slot_index: dict[tuple[str, str], int] = {}
    for draft in drafts:
        norm_detail = " ".join(draft.detail_text.casefold().split())
        if not norm_detail:
            continue
        text_key = f"{draft.owner_id.casefold()}\n{norm_detail}"
        if text_key in seen_text:
            continue
        seen_text.add(text_key)
        if draft.slot_key:
            s_key = (draft.owner_id.casefold(), draft.slot_key.casefold())
            if s_key in slot_index:
                # Later turn in same extraction window supersedes earlier value for same slot_key
                unique[slot_index[s_key]] = draft
                continue
            slot_index[s_key] = len(unique)
        unique.append(draft)
    return unique


def window_to_plain_dialogue(window: ExtractionWindow) -> str:
    lines: list[str] = []
    for msg in window.messages:
        if not isinstance(msg, dict) and not hasattr(msg, "get"):
            continue
        role = str(msg.get("role") or "").strip()
        raw_content = msg.get("content")
        text_str = clean_text(raw_content, max_chars=20000)
        if not text_str:
            continue
        # Preserve already-normalized lines (e.g. `user: ...` / `Mika: ...`)
        if (
            isinstance(raw_content, str)
            and not text_str.lstrip().startswith("{")
            and re.match(r"^[^:\n]{1,64}:\s+", text_str)
        ):
            lines.append(text_str)
            continue
        normalized = clean_text(
            history_payload_to_plain_text([dict(msg)], user_display_name="user"),
            max_chars=20000,
        )
        if normalized:
            lines.append(normalized)
        elif role in {"user", "assistant"}:
            lines.append(f"{role}: {text_str}")
    return "\n".join(lines)


class MemoryExtractor:
    """Extract memories from plain dialogue, implementing MemoryExtractorPort."""

    def __init__(
        self,
        llm_adapter: Any,
        *,
        locale: LocaleInput = None,
        self_persona_name: str = "",
    ) -> None:
        self.llm_adapter = llm_adapter
        self.locale = locale
        self.self_persona_name = clean_text(self_persona_name, max_chars=120)

    def _effective_locale(self, override: LocaleInput = None) -> str:
        return resolve_dynamic_locale(override if override is not None else self.locale)

    def extract_chunk(
        self,
        dialogue: str,
        *,
        default_character_name: str,
        force_character_name: str | None = None,
        locale: LocaleInput = None,
    ) -> list[dict[str, Any]]:
        messages = build_extraction_messages(
            dialogue,
            default_character_name,
            locale=self._effective_locale(locale),
        )
        response = self.llm_adapter.chat(
            messages,
            stream=False,
            response_format={"type": "text"},
        )
        return parse_extracted_memories(
            response,
            default_character_name=default_character_name,
            force_character_name=force_character_name,
        )

    def extract_dialogue(
        self,
        dialogue: str,
        *,
        default_character_name: str,
        force_character_name: str | None = None,
        max_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
        locale: LocaleInput = None,
    ) -> tuple[list[dict[str, Any]], int, int]:
        chunks = chunk_plain_dialogue(dialogue, max_tokens=max_chunk_tokens)
        extracted: list[dict[str, Any]] = []
        active_locale = self._effective_locale(locale)
        for chunk in chunks:
            extracted.extend(
                self.extract_chunk(
                    chunk,
                    default_character_name=default_character_name,
                    force_character_name=force_character_name,
                    locale=active_locale,
                )
            )
        unique, duplicates = deduplicate_memories(extracted)
        return unique, duplicates, len(chunks)

    def extract(
        self,
        window: ExtractionWindow,
        *,
        max_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
        locale: LocaleInput = None,
    ) -> Sequence[MemoryDraft]:
        """Extract dual-granularity MemoryDrafts from an ExtractionWindow."""
        dialogue = window_to_plain_dialogue(window)
        if not dialogue:
            return ()
        chunks = chunk_plain_dialogue(dialogue, max_tokens=max_chunk_tokens)
        collected: list[MemoryDraft] = []
        active_locale = self._effective_locale(locale)
        for chunk in chunks:
            messages = build_structured_extraction_messages(
                chunk,
                character_names=window.character_names,
                now_iso=window.now_iso,
                locale=active_locale,
            )
            response = self.llm_adapter.chat(
                messages,
                stream=False,
                response_format={"type": "text"},
            )
            collected.extend(
                parse_memory_drafts(
                    response,
                    character_names=window.character_names,
                    now_iso=window.now_iso,
                    session_id=window.session_id,
                    turn_seq=window.turn_seq,
                    self_persona_name=self.self_persona_name,
                )
            )
        return tuple(deduplicate_drafts(collected))


def configured_memory_chunk_tokens(config_manager: Any) -> int:
    api_config = getattr(getattr(config_manager, "config", None), "api_config", None)
    try:
        context_tokens = int(getattr(api_config, "max_context_tokens", 0) or 0)
    except (TypeError, ValueError):
        context_tokens = 0
    if context_tokens <= 0:
        return DEFAULT_DIALOGUE_CHUNK_TOKENS
    # Leave room for the extraction instructions and a useful JSON response,
    # while keeping request sizes reasonable even for 128k+ context models.
    return max(512, min(DEFAULT_DIALOGUE_CHUNK_TOKENS, int(context_tokens * 0.6)))


def create_configured_memory_adapter(config_manager: Any) -> Any:
    provider, model, base_url, api_key = config_manager.get_llm_api_config()
    if not provider or not model or not api_key:
        raise RuntimeError("LLM 配置不完整，请先设置供应商、模型和 API Key。")

    from ai.llm.llm_manager import LLMAdapterFactory

    base_kwargs = {
        "llm_provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }
    merged = getattr(config_manager, "merged_llm_factory_kwargs", None)
    kwargs = merged(provider, base_kwargs) if callable(merged) else base_kwargs
    return LLMAdapterFactory.create_adapter(**kwargs)

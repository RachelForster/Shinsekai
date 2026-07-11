"""Shared plain-dialogue to long-term-memory extraction logic."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any

from ai.memory.chunking import DEFAULT_DIALOGUE_CHUNK_TOKENS, chunk_plain_dialogue
from ai.memory.token_estimator import estimate_message_tokens

logger = logging.getLogger(__name__)

EXPECTED_OUTPUT_TOKENS_PER_CHUNK = 1_024
MAX_MEMORIES_PER_CHUNK = 8
MAX_MEMORY_CHARS = 800

_SYSTEM_PROMPT = (
    "You extract durable long-term memories from roleplay chat. "
    "Return only JSON. Do not include prose."
)


def clean_text(value: Any, *, max_chars: int | None = None) -> str:
    text = str(value or "").strip()
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


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


def build_extraction_prompt(dialogue: str, default_character_name: str) -> str:
    name = clean_text(default_character_name, max_chars=120) or "user"
    return (
        "Extract stable, useful long-term memories from the plain dialogue below.\n"
        "Keep only durable facts, preferences, relationships, promises, goals, or character-relevant state.\n"
        "Ignore temporary emotions, filler, one-off phrasing, system narration, and duplicates.\n"
        f"Default character_name is {name!r}.\n"
        "Return JSON array only, each item like:\n"
        '[{"character_name":"Name","memory":"fact to save","confidence":0.85}]\n\n'
        f"Dialogue:\n{clean_text(dialogue)}"
    )


def build_extraction_messages(dialogue: str, default_character_name: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": build_extraction_prompt(dialogue, default_character_name)},
    ]


def estimate_extraction_input_tokens(dialogue: str, default_character_name: str) -> int:
    return estimate_message_tokens(build_extraction_messages(dialogue, default_character_name))


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
        memory = clean_text(row.get("memory") or row.get("content"), max_chars=MAX_MEMORY_CHARS)
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


class MemoryExtractor:
    """Extract memories from already-normalized plain dialogue."""

    def __init__(self, llm_adapter: Any) -> None:
        self.llm_adapter = llm_adapter

    def extract_chunk(
        self,
        dialogue: str,
        *,
        default_character_name: str,
        force_character_name: str | None = None,
    ) -> list[dict[str, Any]]:
        messages = build_extraction_messages(dialogue, default_character_name)
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
    ) -> tuple[list[dict[str, Any]], int, int]:
        chunks = chunk_plain_dialogue(dialogue, max_tokens=max_chunk_tokens)
        extracted: list[dict[str, Any]] = []
        for chunk in chunks:
            extracted.extend(
                self.extract_chunk(
                    chunk,
                    default_character_name=default_character_name,
                    force_character_name=force_character_name,
                )
            )
        unique, duplicates = deduplicate_memories(extracted)
        return unique, duplicates, len(chunks)


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

    from llm.llm_manager import LLMAdapterFactory

    base_kwargs = {
        "llm_provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }
    merged = getattr(config_manager, "merged_llm_factory_kwargs", None)
    kwargs = merged(provider, base_kwargs) if callable(merged) else base_kwargs
    return LLMAdapterFactory.create_adapter(**kwargs)

"""Extract retrievable background setting entries from knowledge source material."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from typing import Any, TypedDict

from ai.llm.template.core import TemplateContext
from ai.llm.template.extraction import (
    KNOWLEDGE_EXTRACTION_SPEC,
    KnowledgeExtractionContext,
)
from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.memory.token_estimator import estimate_message_tokens

logger = logging.getLogger(__name__)

# Preview estimate only; this is not an output limit.
EXPECTED_OUTPUT_TOKENS_PER_CHUNK = 1_024
MAX_KNOWLEDGE_ENTRY_CHARS = 800


class KnowledgeEntry(TypedDict):
    knowledge_id: str
    content: str


class KnowledgeExtractionError(ValueError):
    """The model did not return a complete JSON array of setting entries."""


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
        logger.exception("failed to extract knowledge response")
    return str(response)


def _strip_json_fence(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    return raw


def build_knowledge_extraction_prompt(
    text: str,
    *,
    locale: LocaleInput = None,
) -> str:
    active_locale = resolve_dynamic_locale(locale)
    return KNOWLEDGE_EXTRACTION_SPEC.render_user(
        KnowledgeExtractionContext(
            source_text=str(text or "").strip(),
            locale=active_locale,
        )
    )


def build_knowledge_extraction_messages(
    text: str,
    *,
    locale: LocaleInput = None,
) -> list[dict[str, str]]:
    active_locale = resolve_dynamic_locale(locale)
    return [
        {
            "role": "system",
            "content": KNOWLEDGE_EXTRACTION_SPEC.render_system(
                TemplateContext(locale=active_locale)
            ),
        },
        {
            "role": "user",
            "content": build_knowledge_extraction_prompt(
                text,
                locale=active_locale,
            ),
        },
    ]


def estimate_knowledge_extraction_input_tokens(
    text: str,
    *,
    locale: LocaleInput = None,
) -> int:
    return estimate_message_tokens(
        build_knowledge_extraction_messages(text, locale=locale)
    )


def parse_knowledge_entries(response: Any, *, knowledge_id: str) -> list[KnowledgeEntry]:
    normalized_knowledge_id = str(knowledge_id or "").strip()
    if not normalized_knowledge_id:
        raise ValueError("knowledge id is required")
    raw = _strip_json_fence(extract_response_text(response))
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise KnowledgeExtractionError("资料提取失败：模型未返回完整、有效的 JSON 数组。") from exc
    if not isinstance(parsed, list):
        raise KnowledgeExtractionError("资料提取失败：模型返回的内容不是 JSON 数组。")
    entries: list[KnowledgeEntry] = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        content = row.get("content")
        if isinstance(content, str) and content.strip():
            content = content.strip()[:MAX_KNOWLEDGE_ENTRY_CHARS].rstrip()
            entries.append({"knowledge_id": normalized_knowledge_id, "content": content})
    return entries


def deduplicate_knowledge_entries(
    rows: Iterable[KnowledgeEntry],
) -> tuple[list[KnowledgeEntry], int]:
    unique: list[KnowledgeEntry] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0
    for row in rows:
        content = row["content"].strip()
        if not content:
            continue
        normalized_knowledge_id = row["knowledge_id"].strip()
        key = (normalized_knowledge_id, " ".join(content.casefold().split()))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append({"knowledge_id": normalized_knowledge_id, "content": content})
    return unique, duplicates


class KnowledgeExtractor:
    """Extract setting references independently of personal memory policy."""

    def __init__(
        self,
        llm_adapter: Any,
        *,
        locale: LocaleInput = None,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.locale = locale

    def extract_chunk(
        self,
        text: str,
        *,
        knowledge_id: str,
        locale: LocaleInput = None,
    ) -> list[KnowledgeEntry]:
        if not str(knowledge_id or "").strip():
            raise ValueError("knowledge id is required")
        effective_locale = locale if locale is not None else self.locale
        response = self.llm_adapter.chat(
            build_knowledge_extraction_messages(text, locale=effective_locale),
            stream=False,
            response_format={"type": "text"},
        )
        return parse_knowledge_entries(response, knowledge_id=knowledge_id)

"""AI cast extraction from leading document chunks and local character matching."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import json
import re
from typing import Any

from ai.llm.llm_manager import LLMAdapterFactory
from ai.llm.speculative_dialog import _decode_content
from ai.llm.template.extraction.novel_cast import render_novel_cast_prompts
from ai.llm.template.integrations.localization import resolve_template_locale
from application.chat.history.paths import _state_project_root
from core.document import DocumentRepository
from core.storage.layout import StorageLayout
from sdk.exception.types import AppError

_VALID_ROLES = frozenset({"protagonist", "supporting", "antagonist"})


def _get_opencc() -> Any | None:
    try:
        from opencc import OpenCC

        return OpenCC("t2s")
    except Exception:
        return None


def _norm_key(value: str, cc: Any | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if cc is not None and hasattr(cc, "convert"):
        try:
            converted = str(cc.convert(clean) or "").strip()
            if converted:
                clean = converted
        except Exception:
            pass
    return clean.casefold()


def _parse_cast_json(raw_text: str) -> list[dict[str, Any]]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("Empty LLM response")
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text, flags=re.DOTALL)
    arr_start, arr_end = text.find("["), text.rfind("]")
    obj_start, obj_end = text.find("{"), text.rfind("}")
    candidate = text
    if arr_start >= 0 and arr_end > arr_start and (obj_start < 0 or arr_start < obj_start):
        candidate = text[arr_start : arr_end + 1]
    elif obj_start >= 0 and obj_end > obj_start:
        candidate = text[obj_start : obj_end + 1]
    parsed = json.loads(candidate)
    if isinstance(parsed, dict):
        items = parsed.get("characters") or parsed.get("cast") or []
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise ValueError("Expected JSON array")
    if not isinstance(items, list):
        raise ValueError("Expected character list")
    return [row for row in items if isinstance(row, dict)]


def _available_characters(config_manager: Any) -> list[dict[str, Any]]:
    cfg = getattr(config_manager, "config", None)
    raw_chars = getattr(cfg, "characters", None) or ()
    out: list[dict[str, Any]] = []
    for char in raw_chars:
        name = str(getattr(char, "name", "") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "brief": str(getattr(char, "character_brief", "") or "").strip(),
            }
        )
    return out


def _suggest_local_character(
    name: str,
    aliases: Iterable[str],
    local_names: Sequence[str],
    cc: Any | None,
) -> str:
    by_exact = {item: item for item in local_names}
    by_fold = {item.casefold(): item for item in local_names}
    by_cc = {k: item for item in local_names if (k := _norm_key(item, cc))}
    for probe in (name, *aliases):
        clean = str(probe or "").strip()
        if not clean:
            continue
        if clean in by_exact:
            return by_exact[clean]
        if clean.casefold() in by_fold:
            return by_fold[clean.casefold()]
        normed = _norm_key(clean, cc)
        if normed and normed in by_cc:
            return by_cc[normed]
    return ""


def extract_novel_cast(
    state: Any,
    doc_id: str,
    *,
    max_sample_chunks: int = 5,
    max_sample_chars: int = 5000,
    adapter: Any | None = None,
) -> dict[str, Any]:
    """Extract main characters and suggest local asset bindings from leading chunks."""
    clean_id = str(doc_id or "").strip().lower()
    repo = DocumentRepository(StorageLayout(_state_project_root(state)))
    try:
        manifest = repo.get_manifest(clean_id)
    except ValueError as exc:
        raise AppError(
            "novel.document_not_found",
            params={"docId": clean_id},
            fallback_message="Document not found.",
            http_status=404,
        ) from exc
    if manifest is None:
        raise AppError(
            "novel.document_not_found",
            params={"docId": clean_id},
            fallback_message="Document not found.",
            http_status=404,
        )

    chunks = repo.read_chunks(clean_id)
    excerpts: list[str] = []
    used_chars = 0
    for chunk in chunks[: max(1, int(max_sample_chunks))]:
        snippet = str(chunk.text or "").strip()
        if not snippet:
            continue
        remaining = max(0, int(max_sample_chars) - used_chars)
        if remaining <= 0:
            break
        if len(snippet) > remaining:
            snippet = snippet[:remaining]
        excerpts.append(snippet)
        used_chars += len(snippet)

    config_mgr = getattr(state, "config_manager", None)
    available = _available_characters(config_mgr)
    if not excerpts:
        return {"docId": clean_id, "characters": [], "availableCharacters": available}

    llm_adapter = adapter
    if llm_adapter is None:
        get_llm = getattr(config_mgr, "get_llm_api_config", None)
        if not callable(get_llm):
            raise AppError(
                "novel.llm_not_configured",
                fallback_message="Configure an LLM provider before extracting cast.",
                http_status=400,
            )
        provider, model, base_url, api_key = get_llm()
        if not provider or not model:
            raise AppError(
                "novel.llm_not_configured",
                fallback_message="Configure an LLM provider before extracting cast.",
                http_status=400,
            )
        factory_kwargs = config_mgr.merged_llm_factory_kwargs(
            provider,
            {
                "llm_provider": provider,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            },
        )
        llm_adapter = LLMAdapterFactory.create_adapter(**factory_kwargs)

    locale = resolve_template_locale(config_mgr)
    system_prompt, user_prompt = render_novel_cast_prompts(excerpts, locale=locale)
    try:
        response = llm_adapter.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            tools=None,
        )
        raw_text = _decode_content(llm_adapter, response)
        rows = _parse_cast_json(raw_text)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "novel.cast_extract_failed",
            params={"reason": str(exc)},
            fallback_message=f"Cast extraction failed: {exc}",
            http_status=502,
        ) from exc

    cc = _get_opencc()
    local_names = [entry["name"] for entry in available]
    seen_names: set[str] = set()
    extracted: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name") or "").strip()[:80]
        if not name or name.casefold() in seen_names:
            continue
        seen_names.add(name.casefold())
        raw_aliases = row.get("aliases") or ()
        aliases = [
            clean
            for item in (raw_aliases if isinstance(raw_aliases, (list, tuple)) else ())
            if (clean := str(item or "").strip()[:80]) and clean != name
        ]
        aliases = list(dict.fromkeys(aliases))[:8]
        role = str(row.get("role") or "supporting").strip().lower()
        if role not in _VALID_ROLES:
            role = "supporting"
        description = str(row.get("description") or "").strip()[:160]
        is_first_person = bool(row.get("isFirstPerson", False))
        suggested = _suggest_local_character(name, aliases, local_names, cc)
        extracted.append(
            {
                "name": name,
                "aliases": aliases,
                "role": role,
                "description": description,
                "isFirstPerson": is_first_person,
                "suggestedCharacter": suggested,
            }
        )
        if len(extracted) >= 12:
            break

    return {
        "docId": clean_id,
        "characters": extracted,
        "availableCharacters": available,
    }


__all__ = ["extract_novel_cast"]

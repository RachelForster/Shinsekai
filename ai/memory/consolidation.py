"""EverMemOS `MemScenes` + LightMem sleep-time narrative scene consolidation.

Synthesizes fine-grained `episodic` and `visual` memories accumulated within a
session into a cohesive `kind="scene"` macro-episode strictly during sleep-time
boundaries (`before_compact` or `shutdown`). Original fine-grained memories are
never physically deleted: they decay naturally along Ebbinghaus tiers while the
consolidated `scene` node acts as a high-stability (`S_0 = 30d`) associative hub
for HippoRAG 2 multi-hop PPR recall.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import logging
from typing import Any

from ai.memory.extraction import (
    MAX_GIST_CHARS,
    MAX_MEMORY_CHARS,
    clean_text,
    derive_fallback_gist,
    extract_response_text,
    parse_json_payload,
)
from ai.memory.metadata_tags import pack_system_tags, unpack_system_tags
from sdk.adapters.memory import SCOPE_CHAR_CROSS_SAVE, MemoryDraft

logger = logging.getLogger(__name__)

DEFAULT_MIN_SCENE_EPISODES = 8
DEFAULT_MAX_EPISODES_PER_SCENE = 16

_CONSOLIDATION_SYSTEM_PROMPT = (
    "You consolidate related episodic and visual roleplay memories from one session "
    "into a concise chapter-level scene memory. Return only JSON. Do not include prose."
)

MemoryListFunc = Callable[[str, str], Mapping[str, Any]]


def _build_scene_prompt(
    character_name: str,
    episodes: Sequence[Mapping[str, Any]],
) -> str:
    bullet_rows = []
    for idx, ep in enumerate(episodes, start=1):
        kind_tag = str(ep.get("kind") or "episodic")
        detail = clean_text(ep.get("detail") or ep.get("memory"), max_chars=300)
        bullet_rows.append(f"{idx}. [{kind_tag}] {detail}")
    joined = "\n".join(bullet_rows)
    return (
        f"Synthesize the following {len(episodes)} chronological memories of {character_name!r} "
        "into ONE cohesive chapter-level scene summary (`kind='scene'`).\n"
        "Preserve concrete plot milestones, key shared visual moments, emotional turning points, "
        "and named entities so future recall understands the overall arc.\n"
        "Return a single JSON object only:\n"
        '{"detail":"cohesive chapter summary (<=260 chars)","gist":"brief arc impression (<=35 chars)",'
        '"topics":["tag1","tag2"],"entities":["Entity1","Entity2"],"importance":0.82}\n\n'
        f"Chronological episodes:\n{joined}"
    )


class SceneConsolidator:
    """Sleep-time consolidator producing `kind='scene'` macro-memories."""

    def __init__(
        self,
        llm_adapter: Any,
        *,
        list_func: MemoryListFunc | None = None,
        min_episodes: int = DEFAULT_MIN_SCENE_EPISODES,
        max_episodes_per_scene: int = DEFAULT_MAX_EPISODES_PER_SCENE,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.list_func = list_func
        self.min_episodes = max(3, int(min_episodes))
        self.max_episodes_per_scene = max(self.min_episodes, int(max_episodes_per_scene))

    def consolidate_if_ready(
        self,
        *,
        character_names: Sequence[str],
        session_id: str,
        turn_seq: int | None = None,
    ) -> list[MemoryDraft]:
        """Return `kind='scene'` drafts for characters exceeding `min_episodes` in `session_id`."""
        sid = str(session_id or "").strip()
        if not sid or self.list_func is None:
            return []

        chars = [
            str(c or "").strip()
            for c in dict.fromkeys(character_names)
            if str(c or "").strip() and str(c or "").strip().casefold() not in {"user", "__self__"}
        ]
        if not chars:
            return []

        scene_drafts: list[MemoryDraft] = []
        for char_name in chars:
            draft = self._consolidate_character(
                char_name=char_name,
                session_id=sid,
                turn_seq=turn_seq,
            )
            if draft is not None:
                scene_drafts.append(draft)
        return scene_drafts

    def _consolidate_character(
        self,
        *,
        char_name: str,
        session_id: str,
        turn_seq: int | None,
    ) -> MemoryDraft | None:
        try:
            payload = self.list_func(char_name, session_id)
        except Exception:
            logger.debug("scene consolidator skipped: memory list unavailable", exc_info=True)
            return None

        if not isinstance(payload, Mapping) or payload.get("error") or payload.get("status") == "loading":
            return None
        raw_rows = payload.get("memories")
        if not isinstance(raw_rows, list) or not raw_rows:
            return None

        session_rows = [
            row
            for row in raw_rows
            if isinstance(row, Mapping)
            and str(row.get("sourceSessionId") or "").strip() == session_id
            and not bool(row.get("pinned"))
        ]
        if not session_rows:
            return None

        last_scene_created_at = 0.0
        last_consolidated_seq = -1
        for row in session_rows:
            if str(row.get("kind") or "").strip().lower() != "scene":
                continue
            try:
                last_scene_created_at = max(
                    last_scene_created_at,
                    float(row.get("createdAt") or 0.0),
                )
            except (TypeError, ValueError):
                pass
            if row.get("consolidatedSeq") is not None:
                try:
                    last_consolidated_seq = max(
                        last_consolidated_seq,
                        int(row["consolidatedSeq"]),
                    )
                except (TypeError, ValueError):
                    pass
            else:
                meta = unpack_system_tags(row.get("topicTags") or ())
                if meta.consolidated_seq is not None:
                    last_consolidated_seq = max(last_consolidated_seq, meta.consolidated_seq)

        eligible: list[Mapping[str, Any]] = []
        for row in session_rows:
            kind = str(row.get("kind") or "episodic").strip().lower()
            if kind not in {"episodic", "visual"}:
                continue
            try:
                created_at = float(row.get("createdAt") or 0.0)
            except (TypeError, ValueError):
                created_at = 0.0
            if last_scene_created_at > 0.0 and created_at <= last_scene_created_at:
                continue
            eligible.append(row)

        if len(eligible) < self.min_episodes:
            return None

        eligible.sort(key=lambda r: float(r.get("createdAt") or 0.0))
        slice_rows = eligible[: self.max_episodes_per_scene]

        prompt = _build_scene_prompt(char_name, slice_rows)
        try:
            response = self.llm_adapter.chat(
                [
                    {"role": "system", "content": _CONSOLIDATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                response_format={"type": "text"},
            )
            parsed = parse_json_payload(extract_response_text(response))
        except Exception:
            logger.warning("scene consolidation LLM synthesis failed", exc_info=True)
            return None

        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if not isinstance(parsed, Mapping):
            return None

        detail = clean_text(
            parsed.get("detail") or parsed.get("memory") or parsed.get("summary"),
            max_chars=MAX_MEMORY_CHARS,
        )
        if not detail:
            return None
        gist = clean_text(parsed.get("gist"), max_chars=MAX_GIST_CHARS) or derive_fallback_gist(detail)

        merged_entities: list[str] = []
        seen_ent: set[str] = set()
        raw_ents = parsed.get("entities")
        for source_ents in (
            raw_ents if isinstance(raw_ents, (list, tuple)) else (),
            *(row.get("entities") or () for row in slice_rows),
        ):
            for ent in source_ents:
                val = clean_text(ent, max_chars=60)
                if val and val.casefold() not in seen_ent:
                    seen_ent.add(val.casefold())
                    merged_entities.append(val)
                    if len(merged_entities) >= 10:
                        break
            if len(merged_entities) >= 10:
                break

        merged_topics: list[str] = []
        seen_top: set[str] = set()
        raw_tops = parsed.get("topics")
        for source_tops in (
            raw_tops if isinstance(raw_tops, (list, tuple)) else (),
            *(row.get("topicTags") or () for row in slice_rows),
        ):
            for top in source_tops:
                val = clean_text(top, max_chars=60)
                if val and not val.startswith("__sys:") and val.casefold() not in seen_top:
                    seen_top.add(val.casefold())
                    merged_topics.append(val)
                    if len(merged_topics) >= 6:
                        break
            if len(merged_topics) >= 6:
                break

        try:
            importance = max(0.65, min(0.95, float(parsed.get("importance", 0.82))))
        except (TypeError, ValueError):
            importance = 0.82

        event_at: float | None = None
        for row in reversed(slice_rows):
            if row.get("eventAt") is not None:
                try:
                    event_at = float(row["eventAt"])
                    break
                except (TypeError, ValueError):
                    pass

        watermark_seq = (
            int(turn_seq)
            if turn_seq is not None
            else (last_consolidated_seq + 1 if last_consolidated_seq >= 0 else 0)
        )
        packed_tags = pack_system_tags(
            merged_topics,
            consolidated_seq=watermark_seq,
        )
        return MemoryDraft(
            owner_id=char_name,
            detail_text=detail,
            gist_text=gist,
            scope=SCOPE_CHAR_CROSS_SAVE,
            slot_key="",
            kind="scene",
            topic_tags=packed_tags,
            entities=tuple(merged_entities),
            importance=importance,
            pinned=False,
            event_at=event_at,
            source_session_id=session_id,
            source_turn_seq=None if turn_seq is None else int(turn_seq),
        )


__all__ = [
    "DEFAULT_MAX_EPISODES_PER_SCENE",
    "DEFAULT_MIN_SCENE_EPISODES",
    "MemoryListFunc",
    "SceneConsolidator",
]

"""Memory-R1 / Zep inspired candidate-aware conflict reconciliation.

Runs asynchronously in the background extraction pipeline (never on `before_chat`),
using fast-path similarity gating `[0.52, 0.92)` so clear novel facts (`< 0.52`)
and exact duplicates (`>= 0.92`) incur zero extra LLM calls, while ambiguous
updates, drifted `slot_key`s, and explicit retractions are resolved in a single
batched JSON decision (`ADD` | `SUPERSEDE` | `INVALIDATE` | `NOOP`) with 100%
timeline-rollback reversibility.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import json
import logging
import re
from typing import Any

from ai.memory.extraction import clean_text, extract_response_text, parse_json_payload
from ai.memory.metadata_tags import pack_system_tags, unpack_system_tags
from sdk.adapters.memory import SCOPE_CHAR_CANON, MemoryDraft

logger = logging.getLogger(__name__)

DEFAULT_LOW_CONFLICT_GATE = 0.52
DEFAULT_HIGH_DUPLICATE_GATE = 0.92
DEFAULT_CANDIDATE_LIMIT = 5

_CORRECTION_CUE_RE = re.compile(
    r"(?:戒了|戒掉|取消了|改(?:口|喝|吃|用|去|玩|学|住|成|为|做)|换(?:成|到|去)|"
    r"不(?:去|喝|吃|玩|用|住)[^，。！？!?\n]{0,12}了|"
    r"之前说错|记错了|其实我不|其实没|不再|不是真的|骗你的|更正一下|"
    r"\bno\s+longer\b|\bused\s+to\b|\bchanged\s+my\s+mind\b|\bactually\s+i\s+don'?t\b|"
    r"\bstopped\b|\bquit\b|やめた|実は違う|やっぱりやめ)",
    re.IGNORECASE,
)

_RECONCILE_SYSTEM_PROMPT = (
    "You reconcile newly extracted roleplay memory drafts against existing stored memories. "
    "Return only a JSON array of decisions. Do not include prose."
)

CandidateFetcher = Callable[[MemoryDraft, int], Sequence[Mapping[str, Any]]]


def has_correction_or_negation_cue(text: str) -> bool:
    """Return True when text contains explicit preference-update, correction, or retraction cues."""
    return bool(_CORRECTION_CUE_RE.search(str(text or "")))


def _char_bigram_jaccard(a: str, b: str) -> float:
    sa = "".join(str(a or "").casefold().split())
    sb = "".join(str(b or "").casefold().split())
    if not sa or not sb:
        return 0.0
    if sa == sb:
        return 1.0
    ga = {sa[i : i + 2] for i in range(max(1, len(sa) - 1))}
    gb = {sb[i : i + 2] for i in range(max(1, len(sb) - 1))}
    union = len(ga | gb)
    return float(len(ga & gb)) / float(union) if union else 0.0


def _slot_namespace(slot_key: str) -> str:
    raw = str(slot_key or "").strip().casefold()
    if ":" not in raw:
        return ""
    return raw.split(":", 1)[0].strip()


def _normalize_candidates(
    draft: MemoryDraft,
    raw_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid or cid in seen:
            continue
        if bool(row.get("pinned")) or str(row.get("scope") or "") == SCOPE_CHAR_CANON:
            continue
        kind = str(row.get("kind") or "episodic").strip().lower()
        if kind in {"canon", "retraction"}:
            continue
        detail = clean_text(
            row.get("detail") or row.get("memory") or row.get("content"),
            max_chars=600,
        )
        if not detail:
            continue
        raw_vec = (
            row["vectorScore"]
            if "vectorScore" in row and row["vectorScore"] is not None
            else row.get("score", 0.0)
        )
        try:
            vec_score = float(raw_vec or 0.0)
        except (TypeError, ValueError):
            vec_score = 0.0
        try:
            hybrid_score = float(row.get("score", vec_score) or 0.0)
        except (TypeError, ValueError):
            hybrid_score = vec_score
        lexical = _char_bigram_jaccard(draft.detail_text, detail)
        dup_score = max(0.0, min(1.0, max(vec_score, lexical)))
        conflict_score = max(dup_score, min(0.85, hybrid_score * 0.75))
        seen.add(cid)
        out.append(
            {
                "id": cid,
                "detail": detail,
                "slot_key": str(row.get("slotKey") or row.get("slot_key") or "").strip(),
                "kind": kind,
                "score": round(dup_score, 4),
                "conflict_score": round(conflict_score, 4),
            }
        )
    out.sort(key=lambda item: (item["conflict_score"], item["score"]), reverse=True)
    return out


def _build_reconciliation_prompt(
    batch: Sequence[tuple[int, MemoryDraft, list[dict[str, Any]]]],
    *,
    dialogue_hint: str = "",
) -> str:
    items_payload = []
    for idx, draft, cands in batch:
        items_payload.append(
            {
                "index": idx,
                "draft": {
                    "owner": draft.owner_id,
                    "kind": draft.kind,
                    "slot_key": draft.slot_key,
                    "detail": draft.detail_text,
                },
                "existing_candidates": [
                    {
                        "id": c["id"],
                        "kind": c["kind"],
                        "slot_key": c["slot_key"],
                        "detail": c["detail"],
                        "similarity": c["score"],
                    }
                    for c in cands
                ],
            }
        )
    hint_block = (
        f"Recent dialogue context:\n{clean_text(dialogue_hint, max_chars=1500)}\n\n"
        if dialogue_hint
        else ""
    )
    return (
        "Decide how each new memory `draft` relates to its `existing_candidates`.\n"
        "Actions:\n"
        "- 'ADD': New distinct fact/event that coexists with all existing candidates.\n"
        "- 'SUPERSEDE': The draft updates, replaces, or refines outdated state/preference in "
        "`target_ids` (even if `slot_key` differs).\n"
        "- 'INVALIDATE': The user retracted/negated the false prior memory in `target_ids` "
        "without stating a new positive fact.\n"
        "- 'NOOP': The draft is already fully captured by an existing candidate.\n"
        "Only reference `id` values present in that item's `existing_candidates`.\n"
        "Return JSON array only, shaped like:\n"
        '[{"index":0,"action":"ADD|SUPERSEDE|INVALIDATE|NOOP","target_ids":["id1"]}]\n\n'
        f"{hint_block}"
        f"Items:\n{json.dumps(items_payload, ensure_ascii=False)}"
    )


def _attach_supersedes(
    draft: MemoryDraft,
    target_ids: Sequence[str],
    *,
    inherited_slot_key: str = "",
) -> MemoryDraft:
    meta = unpack_system_tags(draft.topic_tags)
    merged_supersedes = tuple(dict.fromkeys([*meta.supersedes_ids, *target_ids]))
    packed = pack_system_tags(
        meta.public_tags,
        valid_until=meta.valid_until,
        supersedes_ids=merged_supersedes,
        visual_ref=meta.visual_ref,
        consolidated_seq=meta.consolidated_seq,
    )
    eff_slot = draft.slot_key or inherited_slot_key
    return replace(draft, slot_key=eff_slot, topic_tags=packed)


class CandidateReconciler:
    """Reconcile extracted `MemoryDraft`s against existing memories via Memory-R1 actions."""

    def __init__(
        self,
        llm_adapter: Any,
        *,
        candidate_fetcher: CandidateFetcher | None = None,
        low_gate: float = DEFAULT_LOW_CONFLICT_GATE,
        high_gate: float = DEFAULT_HIGH_DUPLICATE_GATE,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.candidate_fetcher = candidate_fetcher
        self.low_gate = float(low_gate)
        self.high_gate = float(high_gate)
        self.candidate_limit = max(1, int(candidate_limit))

    def reconcile(
        self,
        drafts: Sequence[MemoryDraft],
        *,
        dialogue_text: str = "",
    ) -> list[MemoryDraft]:
        """Return reconciled drafts ready for `MemoryWriteQueue` / `MemoryOrchestrator`."""
        if not drafts or self.candidate_fetcher is None:
            return [d for d in drafts if str(d.kind or "").lower() != "retraction"]

        window_has_correction = has_correction_or_negation_cue(dialogue_text)
        resolved: dict[int, MemoryDraft | None] = {}
        ambiguous_batch: list[tuple[int, MemoryDraft, list[dict[str, Any]]]] = []

        for idx, draft in enumerate(drafts):
            kind_norm = str(draft.kind or "episodic").strip().lower()
            draft_has_correction = window_has_correction or has_correction_or_negation_cue(
                draft.detail_text
            )
            try:
                raw_cands = self.candidate_fetcher(draft, self.candidate_limit)
            except Exception:
                logger.debug("candidate fetch skipped during reconciliation", exc_info=True)
                raw_cands = ()

            cands = _normalize_candidates(draft, raw_cands)
            if not cands:
                # Nothing stored yet: retractions are no-ops, normal drafts fast-path ADD (0 LLM calls).
                resolved[idx] = None if kind_norm == "retraction" else draft
                continue

            best_dup_score = max(float(c["score"]) for c in cands)
            best_conflict_score = max(float(c["conflict_score"]) for c in cands)
            norm_draft_text = " ".join(draft.detail_text.casefold().split())
            exact_same = any(
                " ".join(c["detail"].casefold().split()) == norm_draft_text for c in cands
            )
            if kind_norm != "retraction" and exact_same:
                resolved[idx] = None
                continue

            # If exact same `slot_key` already matches a candidate, underlying `upsert` handles
            # slot superseding deterministically without needing an extra LLM call!
            if (
                kind_norm != "retraction"
                and draft.slot_key
                and any(
                    c["slot_key"] and c["slot_key"].casefold() == draft.slot_key.casefold()
                    for c in cands
                )
            ):
                resolved[idx] = draft
                continue

            if (
                kind_norm != "retraction"
                and not draft_has_correction
                and best_dup_score >= self.high_gate
            ):
                resolved[idx] = None
                continue

            draft_ns = _slot_namespace(draft.slot_key)
            shares_slot_ns = bool(
                draft_ns and any(_slot_namespace(c["slot_key"]) == draft_ns for c in cands)
            )
            needs_llm = (
                kind_norm == "retraction"
                or (self.low_gate <= best_dup_score < self.high_gate)
                or (draft_has_correction and best_conflict_score >= 0.18)
                or (shares_slot_ns and best_conflict_score >= 0.28)
            )
            if not needs_llm:
                resolved[idx] = draft
                continue

            ambiguous_batch.append((idx, draft, cands))

        if ambiguous_batch:
            self._arbitrate_batch(ambiguous_batch, resolved, dialogue_hint=dialogue_text)

        return [
            item
            for idx in range(len(drafts))
            if (item := resolved.get(idx)) is not None
        ]

    def _arbitrate_batch(
        self,
        batch: Sequence[tuple[int, MemoryDraft, list[dict[str, Any]]]],
        resolved: dict[int, MemoryDraft | None],
        *,
        dialogue_hint: str = "",
    ) -> None:
        prompt = _build_reconciliation_prompt(batch, dialogue_hint=dialogue_hint)
        messages = [
            {"role": "system", "content": _RECONCILE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        decisions_by_idx: dict[int, dict[str, Any]] = {}
        try:
            response = self.llm_adapter.chat(
                messages,
                stream=False,
                response_format={"type": "text"},
            )
            parsed = parse_json_payload(extract_response_text(response))
            if isinstance(parsed, dict):
                parsed = parsed.get("decisions") or parsed.get("items") or []
            if isinstance(parsed, list):
                for row in parsed:
                    if isinstance(row, dict) and isinstance(row.get("index"), int):
                        decisions_by_idx[int(row["index"])] = row
        except Exception:
            logger.warning("background memory reconciliation LLM call failed; keeping ADD fallback", exc_info=True)

        for idx, draft, cands in batch:
            kind_norm = str(draft.kind or "episodic").strip().lower()
            cand_by_id = {c["id"]: c for c in cands}
            row = decisions_by_idx.get(idx)
            if row is None:
                resolved[idx] = None if kind_norm == "retraction" else draft
                continue

            action = str(row.get("action") or "ADD").strip().upper()
            raw_targets = row.get("target_ids") or row.get("targetIds") or ()
            if isinstance(raw_targets, str):
                raw_targets = (raw_targets,)
            valid_targets = [
                tid
                for raw_tid in (raw_targets if isinstance(raw_targets, (list, tuple)) else ())
                if (tid := str(raw_tid or "").strip()) in cand_by_id
            ]

            if action == "NOOP":
                resolved[idx] = None
            elif action == "INVALIDATE":
                if not valid_targets and kind_norm == "retraction" and cands:
                    valid_targets = [cands[0]["id"]]
                if not valid_targets:
                    resolved[idx] = None
                else:
                    tombstone = replace(
                        draft,
                        kind="retraction",
                        slot_key="",
                        importance=0.1,
                    )
                    resolved[idx] = _attach_supersedes(tombstone, valid_targets)
            elif action == "SUPERSEDE":
                if not valid_targets:
                    resolved[idx] = None if kind_norm == "retraction" else draft
                else:
                    inherited_slot = ""
                    for tid in valid_targets:
                        cand_slot = cand_by_id[tid]["slot_key"]
                        if cand_slot:
                            inherited_slot = cand_slot
                            break
                    eff_draft = (
                        replace(draft, kind="profile")
                        if kind_norm == "retraction"
                        else draft
                    )
                    resolved[idx] = _attach_supersedes(
                        eff_draft,
                        valid_targets,
                        inherited_slot_key=inherited_slot,
                    )
            else:
                resolved[idx] = None if kind_norm == "retraction" else draft


__all__ = [
    "CandidateFetcher",
    "CandidateReconciler",
    "DEFAULT_CANDIDATE_LIMIT",
    "DEFAULT_HIGH_DUPLICATE_GATE",
    "DEFAULT_LOW_CONFLICT_GATE",
    "has_correction_or_negation_cue",
]

"""HippoRAG 2 inspired scoped bipartite Personalized PageRank (PPR) ranker.

Operates strictly over the `MemoryRecord` slice returned for a single isolated
`(MemoryRepository, MemoryScopeFilter)` target so multi-hop associative recall
(`Memory A -> Entity X -> Memory B -> Entity Y -> Memory C`) never crosses
character or save-isolation boundaries and requires zero schema/port changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math

import numpy as np

from ai.memory.metadata_tags import strip_system_tags
from sdk.adapters.memory import MemoryRecord

DEFAULT_PPR_DAMPING = 0.85
DEFAULT_PPR_ITERATIONS = 10
DEFAULT_MIN_PPR_SCORE = 0.022
DEFAULT_MAX_GRAPH_RECORDS = 300

_SELF_CONCEPT_ALIASES = frozenset(
    {"", "user", "__self__", "你", "我", "自设", "player", "human", "玩家", "用户"}
)


@dataclass(frozen=True, slots=True)
class PPRHit:
    """Multi-hop associative recall candidate ranked by scoped bipartite PPR."""

    record: MemoryRecord
    ppr_score: float
    calibrated_relevance: float


def _normalize_concept(raw: str) -> str:
    return " ".join(str(raw or "").strip().casefold().split())


def calibrate_ppr_relevance(
    ppr_score: float,
    *,
    min_ppr_score: float = DEFAULT_MIN_PPR_SCORE,
) -> float:
    """Map raw stationary PPR mass on non-seed nodes into `[0.39, 0.62]` relevance."""
    score = float(ppr_score)
    floor = max(1e-6, float(min_ppr_score))
    if score < floor or not math.isfinite(score):
        return 0.0
    denom = math.log1p(0.50 / floor)
    ratio = min(1.0, math.log1p(score / floor) / denom) if denom > 0.0 else 0.0
    return round(0.39 + 0.23 * ratio, 6)


def run_scoped_bipartite_ppr(
    records: Sequence[MemoryRecord],
    *,
    seed_weights: Mapping[str, float],
    damping: float = DEFAULT_PPR_DAMPING,
    iterations: int = DEFAULT_PPR_ITERATIONS,
    min_ppr_score: float = DEFAULT_MIN_PPR_SCORE,
    limit: int = 8,
) -> tuple[tuple[PPRHit, ...], bool]:
    """Run damped bipartite PPR over `(MemoryRecord <-> Concept)` within one scope.

    Returns `(ranked_non_seed_hits, graph_had_bridging_concepts)` so callers can
    smoothly fall back to `repo.expand_entities` on custom plugin repositories
    that do not populate `entities` in `list_by_scope`.
    """
    if not records or not seed_weights or limit <= 0:
        return (), False

    active: list[MemoryRecord] = []
    seen_ids: set[str] = set()
    for rec in records:
        if rec.superseded_by is not None:
            continue
        if str(rec.kind or "").strip().lower() == "retraction":
            continue
        rid = str(rec.id or "").strip()
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        active.append(rec)

    n_mem = len(active)
    if n_mem < 2:
        return (), False

    id_to_idx = {rec.id: idx for idx, rec in enumerate(active)}
    p_vec = np.zeros(n_mem, dtype=np.float32)
    seed_indices: set[int] = set()
    for seed_id, raw_w in seed_weights.items():
        idx = id_to_idx.get(str(seed_id or "").strip())
        if idx is not None and float(raw_w) > 0.0:
            p_vec[idx] = max(float(p_vec[idx]), float(raw_w))
            seed_indices.add(idx)

    total_seed = float(p_vec.sum())
    if total_seed <= 1e-9:
        return (), False
    p_vec /= total_seed

    # Extract per-memory concept lists: `("ent", norm)` (1.0) and `("tag", norm)` (0.45)
    mem_concepts: list[list[tuple[tuple[str, str], float]]] = []
    doc_freq: dict[tuple[str, str], int] = {}

    for rec in active:
        owner_norm = _normalize_concept(rec.owner_id)
        local_map: dict[tuple[str, str], float] = {}

        for ent in rec.entities:
            norm = _normalize_concept(ent)
            if not norm:
                continue
            key = ("ent", norm)
            self_mult = (
                0.15
                if (norm in _SELF_CONCEPT_ALIASES or (owner_norm and norm == owner_norm))
                else 1.0
            )
            local_map[key] = max(local_map.get(key, 0.0), 1.0 * self_mult)

        for tag in strip_system_tags(rec.topic_tags):
            norm = _normalize_concept(tag)
            if not norm:
                continue
            key = ("tag", norm)
            self_mult = (
                0.15
                if (norm in _SELF_CONCEPT_ALIASES or (owner_norm and norm == owner_norm))
                else 1.0
            )
            local_map[key] = max(local_map.get(key, 0.0), 0.45 * self_mult)

        row_items = list(local_map.items())
        mem_concepts.append(row_items)
        for key, _mult in row_items:
            doc_freq[key] = doc_freq.get(key, 0) + 1

    # Retain only concepts bridging >= 2 memories
    bridging_keys = [key for key, df in doc_freq.items() if df >= 2]
    if not bridging_keys:
        return (), False

    c_to_idx = {key: idx for idx, key in enumerate(bridging_keys)}
    n_con = len(bridging_keys)
    eff_corpus = float(max(n_mem, 12))

    # Smoothed Inverse Entity Frequency (IEF) + hub dampening on ubiquitous concepts
    ief_weights = np.empty(n_con, dtype=np.float32)
    concept_retention = np.ones(n_con, dtype=np.float32)
    for c_idx, key in enumerate(bridging_keys):
        df = doc_freq[key]
        ief_weights[c_idx] = math.log1p(eff_corpus / (1.0 + float(df)))
        if n_mem >= 8:
            freq = float(df) / float(n_mem)
            if freq > 0.35:
                # Dampen walks passing through ubiquitous hub concepts (>35% of corpus)
                concept_retention[c_idx] = max(0.08, 1.0 - (freq - 0.35) / 0.65)

    b_mat = np.zeros((n_mem, n_con), dtype=np.float32)
    imp_weights = np.empty(n_mem, dtype=np.float32)
    for m_idx, rec in enumerate(active):
        imp = max(0.0, min(1.0, float(rec.importance)))
        imp_weights[m_idx] = 0.70 + 0.30 * imp
        for key, mult in mem_concepts[m_idx]:
            c_idx = c_to_idx.get(key)
            if c_idx is not None:
                b_mat[m_idx, c_idx] = float(mult) * ief_weights[c_idx]

    # Row-normalize Memory -> Concept transition matrix
    row_sums = b_mat.sum(axis=1, keepdims=True)
    p_m2c = np.divide(
        b_mat,
        row_sums,
        out=np.zeros_like(b_mat),
        where=row_sums > 1e-12,
    )

    # Row-normalize Concept -> Memory transition matrix (weighted by target importance & hub retention)
    c2m_raw = b_mat.T * imp_weights[np.newaxis, :]
    c_sums = c2m_raw.sum(axis=1, keepdims=True)
    p_c2m = np.divide(
        c2m_raw,
        c_sums,
        out=np.zeros_like(c2m_raw),
        where=c_sums > 1e-12,
    )
    p_c2m *= concept_retention[:, np.newaxis]

    alpha = max(0.01, min(0.99, 1.0 - float(damping)))
    walk_prob = 1.0 - alpha
    n_iters = max(1, int(iterations))

    r_vec = p_vec.copy()
    for _ in range(n_iters):
        v_con = r_vec @ p_m2c
        r_step = v_con @ p_c2m
        leaked = max(0.0, 1.0 - float(r_step.sum()))
        r_vec = (alpha + walk_prob * leaked) * p_vec + walk_prob * r_step

    candidates: list[PPRHit] = []
    for m_idx, score in enumerate(r_vec):
        if m_idx in seed_indices:
            continue
        ppr_val = float(score)
        if ppr_val < min_ppr_score:
            continue
        rel = calibrate_ppr_relevance(ppr_val, min_ppr_score=min_ppr_score)
        if rel <= 0.0:
            continue
        candidates.append(
            PPRHit(
                record=active[m_idx],
                ppr_score=ppr_val,
                calibrated_relevance=rel,
            )
        )

    candidates.sort(
        key=lambda item: (
            item.ppr_score,
            item.record.importance,
            item.record.created_at,
        ),
        reverse=True,
    )
    return tuple(candidates[: max(1, int(limit))]), True


__all__ = [
    "DEFAULT_MAX_GRAPH_RECORDS",
    "DEFAULT_MIN_PPR_SCORE",
    "DEFAULT_PPR_DAMPING",
    "DEFAULT_PPR_ITERATIONS",
    "PPRHit",
    "calibrate_ppr_relevance",
    "run_scoped_bipartite_ppr",
]

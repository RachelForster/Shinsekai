"""MemoryOrchestrator composing narrow SOLID ports for recall, decay, and save isolation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import time
from typing import Any

import numpy as np

from ai.memory.deduplication import find_duplicate_memory, semantic_deduplication_threshold
from ai.memory.ebbinghaus import EbbinghausRetentionPolicy
from ai.memory.rule_recall_planner import RuleRecallPlanner
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    SCOPE_SELF_PUBLIC,
    CandidateHit,
    EmbeddingProvider,
    IngestReport,
    MemoryCandidateQuery,
    MemoryContextBlock,
    MemoryDraft,
    MemoryExtractorPort,
    MemoryRecord,
    MemoryRepository,
    MemoryScopeFilter,
    RecallPlanner,
    RetentionPolicy,
    RetentionState,
    TurnRecallInput,
)
from sdk.adapters.session import (
    MEMORY_MODE_INHERIT_READONLY,
    MEMORY_MODE_ISOLATED,
    MEMORY_MODE_SHARED,
    normalize_memory_mode,
)

INJECTION_HEADER = "[Shinsekai long-term memory context]"
DEFAULT_MIN_RELEVANCE = 0.38
DEFAULT_CANON_MIN_RELEVANCE = 0.48
DEFAULT_CANON_MIN_SCORE = 0.60
DEFAULT_DORMANT_AWAKEN_VECTOR_SIM = 0.82
DEFAULT_DORMANT_AWAKEN_FTS_SCORE = 0.72
DEFAULT_MAX_DORMANT_AWAKENED = 2

_SELF_OWNER_ALIASES: frozenset[str] = frozenset(
    {"", "user", "__self__", "你", "我", "自设", "player", "human"}
)
_SYSTEM_SPEAKERS: frozenset[str] = frozenset(
    {"cot", "narr", "choice", "stat", "scene", "bgm", "cg", "system"}
)


def is_roleplay_player_persona(player_character: str | None) -> bool:
    """Return True when the user is roleplaying as a named non-self character."""
    cleaned = str(player_character or "").strip()
    if not cleaned:
        return False
    return cleaned.casefold() not in _SELF_OWNER_ALIASES


def normalize_character_owners(names: Sequence[str]) -> tuple[str, ...]:
    """Deduplicate active character names while excluding user/system placeholders."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw or "").strip()
        if not name:
            continue
        low = name.casefold()
        if low in _SELF_OWNER_ALIASES or low in _SYSTEM_SPEAKERS:
            continue
        if low not in seen:
            seen.add(low)
            out.append(name)
    return tuple(out)


def _is_canon_memory(
    record: MemoryRecord,
    retention_state: RetentionState | None = None,
) -> bool:
    """Return True for pinned / canon memories (character core experiences & pinned facts)."""
    if retention_state is not None and retention_state.tier == "canon":
        return True
    return bool(
        record.pinned
        or record.scope == SCOPE_CHAR_CANON
        or record.kind == "canon"
    )


def _normalize_vec(raw: Any | None) -> np.ndarray | None:
    if raw is None:
        return None
    arr = np.asarray(raw, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return None
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-12 or not np.isfinite(norm):
        return None
    return arr / norm


def _max_cosine_against_queries(embedding: Any | None, query_vectors: Sequence[Any]) -> float:
    """Compute max cosine similarity of a record embedding against normalized query clauses."""
    doc_vec = _normalize_vec(embedding)
    if doc_vec is None or not query_vectors:
        return 0.0
    best = 0.0
    for raw_q in query_vectors:
        q_vec = _normalize_vec(raw_q)
        if q_vec is not None and q_vec.shape == doc_vec.shape:
            best = max(best, float(np.dot(doc_vec, q_vec)))
    return best


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    repo: MemoryRepository
    record: MemoryRecord
    retention_state: RetentionState
    vector_score: float
    fts_score: float
    relevance: float
    final_score: float
    awakened_dormant: bool = False


class MemoryOrchestrator:
    """Coordinates hybrid recall, Ebbinghaus clarity tiers, 1-hop entities, and 3 save modes."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        global_repo: MemoryRepository,
        save_repo: MemoryRepository | None = None,
        retention_policy: RetentionPolicy | None = None,
        recall_planner: RecallPlanner | None = None,
        extractor: MemoryExtractorPort | None = None,
        min_relevance: float = DEFAULT_MIN_RELEVANCE,
        canon_min_relevance: float = DEFAULT_CANON_MIN_RELEVANCE,
        canon_min_score: float = DEFAULT_CANON_MIN_SCORE,
        dormant_awaken_vector_sim: float = DEFAULT_DORMANT_AWAKEN_VECTOR_SIM,
        dormant_awaken_fts_score: float = DEFAULT_DORMANT_AWAKEN_FTS_SCORE,
        max_dormant_awakened: int = DEFAULT_MAX_DORMANT_AWAKENED,
    ) -> None:
        self.embedder = embedder
        self.global_repo = global_repo
        self.save_repo = save_repo
        self.retention_policy: RetentionPolicy = retention_policy or EbbinghausRetentionPolicy()
        self.recall_planner: RecallPlanner = recall_planner or RuleRecallPlanner()
        self.extractor = extractor
        self.min_relevance = float(min_relevance)
        self.canon_min_relevance = float(canon_min_relevance)
        self.canon_min_score = float(canon_min_score)
        self.dormant_awaken_vector_sim = float(dormant_awaken_vector_sim)
        self.dormant_awaken_fts_score = float(dormant_awaken_fts_score)
        self.max_dormant_awakened = max(0, int(max_dormant_awakened))

    def _effective_save_repo(self, override: MemoryRepository | None) -> MemoryRepository | None:
        return override if override is not None else self.save_repo

    def _evaluate_retention(
        self,
        record: MemoryRecord,
        *,
        now_ts: float,
        offline_gap_seconds: float = 0.0,
    ) -> RetentionState:
        if isinstance(self.retention_policy, EbbinghausRetentionPolicy):
            return self.retention_policy.evaluate(
                record,
                now_ts=now_ts,
                offline_gap_seconds=offline_gap_seconds,
            )
        return self.retention_policy.evaluate(record, now_ts=now_ts)

    def _build_read_targets(
        self,
        *,
        memory_mode: str,
        active_character_names: Sequence[str],
        session_id: str,
        save_repo: MemoryRepository | None,
        include_self_public: bool = True,
        event_from: float | None = None,
        event_to: float | None = None,
    ) -> list[tuple[MemoryRepository, MemoryScopeFilter]]:
        """Build strictly isolated `(repo, filter)` pairs preventing cross-character telepathy."""
        mode = normalize_memory_mode(memory_mode)
        chars = normalize_character_owners(active_character_names)
        sid = str(session_id or "").strip() or None
        save_owners = ("__self__", *chars) if include_self_public else chars
        targets: list[tuple[MemoryRepository, MemoryScopeFilter]] = []

        if mode == MEMORY_MODE_ISOLATED:
            if save_owners and (save_repo is not None or sid is not None):
                targets.append(
                    (
                        save_repo if save_repo is not None else self.global_repo,
                        MemoryScopeFilter(
                            scopes=(SCOPE_SAVE_ISOLATED,),
                            owner_ids=save_owners,
                            session_id=sid,
                            event_from=event_from,
                            event_to=event_to,
                        ),
                    )
                )
            if chars:
                # Character factory canon lore remains readable without leaking cross-save episodes
                targets.append(
                    (
                        self.global_repo,
                        MemoryScopeFilter(
                            scopes=(SCOPE_CHAR_CANON,),
                            owner_ids=chars,
                        ),
                    )
                )
            return targets

        # `shared` and `inherit_readonly` both read global public + active character + per-save
        if include_self_public:
            targets.append(
                (
                    self.global_repo,
                    MemoryScopeFilter(
                        scopes=(SCOPE_SELF_PUBLIC,),
                        owner_ids=("__self__",),
                        event_from=event_from,
                        event_to=event_to,
                    ),
                )
            )
        if chars:
            targets.append(
                (
                    self.global_repo,
                    MemoryScopeFilter(
                        scopes=(SCOPE_CHAR_CANON, SCOPE_CHAR_CROSS_SAVE),
                        owner_ids=chars,
                        event_from=event_from,
                        event_to=event_to,
                    ),
                )
            )
        if save_owners and (save_repo is not None or sid is not None):
            targets.append(
                (
                    save_repo if save_repo is not None else self.global_repo,
                    MemoryScopeFilter(
                        scopes=(SCOPE_SAVE_ISOLATED,),
                        owner_ids=save_owners,
                        session_id=sid,
                        event_from=event_from,
                        event_to=event_to,
                    ),
                )
            )
        return targets

    def resolve_write_target(
        self,
        draft: MemoryDraft,
        *,
        memory_mode: str = MEMORY_MODE_SHARED,
        save_repo: MemoryRepository | None = None,
        player_character: str = "",
    ) -> tuple[MemoryRepository, str, str]:
        """Resolve `(target_repo, scope, owner_id)` for a draft under the active save mode."""
        mode = normalize_memory_mode(memory_mode)
        eff_save_repo = self._effective_save_repo(save_repo)
        raw_owner = str(draft.owner_id or "").strip()
        persona_name = str(player_character or "").strip()
        roleplay_persona = is_roleplay_player_persona(persona_name)

        is_player_fact = (
            raw_owner.casefold() in _SELF_OWNER_ALIASES
            or draft.scope == SCOPE_SELF_PUBLIC
            or (roleplay_persona and raw_owner.casefold() == persona_name.casefold())
        )

        # Explicit character canon configuration goes to global repo only in shared mode
        if mode in {MEMORY_MODE_ISOLATED, MEMORY_MODE_INHERIT_READONLY}:
            if eff_save_repo is None:
                raise ValueError(
                    f"save_repo is required when memory_mode is {mode!r}"
                )
            owner = "__self__" if is_player_fact else raw_owner
            return (eff_save_repo, SCOPE_SAVE_ISOLATED, owner or "__self__")

        # Shared mode: when roleplaying a named persona (non-self), strictly keep runtime
        # memories in the save so neither human `self_public` nor `char_cross_save` is polluted!
        if roleplay_persona and not (draft.scope == SCOPE_CHAR_CANON or draft.kind == "canon"):
            target = eff_save_repo if eff_save_repo is not None else self.global_repo
            owner = "__self__" if is_player_fact else (raw_owner or "__self__")
            return (target, SCOPE_SAVE_ISOLATED, owner)

        if is_player_fact:
            return (self.global_repo, SCOPE_SELF_PUBLIC, "__self__")

        if draft.scope == SCOPE_SAVE_ISOLATED and eff_save_repo is not None:
            return (eff_save_repo, SCOPE_SAVE_ISOLATED, raw_owner)
        if draft.scope == SCOPE_CHAR_CANON or draft.kind == "canon":
            return (self.global_repo, SCOPE_CHAR_CANON, raw_owner)
        return (self.global_repo, SCOPE_CHAR_CROSS_SAVE, raw_owner)

    def recall_for_turn(
        self,
        turn_input: TurnRecallInput,
        *,
        save_repo: MemoryRepository | None = None,
    ) -> MemoryContextBlock:
        """Execute zero-latency recall plan, hybrid search, entity hop, and Ebbinghaus gating."""
        now_ts = float(turn_input.now_ts) if turn_input.now_ts > 0 else time.time()
        plan = self.recall_planner.plan(replace(turn_input, now_ts=now_ts))
        if not plan.should_recall:
            return MemoryContextBlock(rendered="", recalled_ids=())

        eff_save_repo = self._effective_save_repo(save_repo)
        q_vecs: tuple[Any, ...] = ()
        if plan.query_clauses:
            mat = self.embedder.embed_documents(list(plan.query_clauses))
            q_vecs = tuple(mat[idx] for idx in range(len(plan.query_clauses)))

        has_time_window = plan.event_from is not None or plan.event_to is not None
        targets = self._build_read_targets(
            memory_mode=turn_input.memory_mode,
            active_character_names=turn_input.active_character_names,
            session_id=turn_input.session_id,
            save_repo=eff_save_repo,
            include_self_public=True,
            event_from=plan.event_from,
            event_to=plan.event_to,
        )
        if not targets:
            return MemoryContextBlock(rendered="", recalled_ids=())

        candidate_limit = max(int(plan.limit) * 4, 24)
        collected: dict[tuple[int, str], tuple[MemoryRepository, CandidateHit, bool, bool, bool]] = {}

        for repo, scope_filter in targets:
            hits = repo.search_candidates(
                MemoryCandidateQuery(
                    scope_filter=scope_filter,
                    query_vectors=q_vecs,
                    keyword_query=plan.keyword_query,
                    limit=candidate_limit,
                )
            )
            is_temporal = (
                scope_filter.event_from is not None or scope_filter.event_to is not None
            )
            for hit in hits:
                key = (id(repo), hit.record.id)
                collected[key] = (repo, hit, is_temporal, False, False)

        # If a time-bounded query found nothing, also check timeless/unbounded memories softly
        if has_time_window and not collected:
            unbounded_targets = self._build_read_targets(
                memory_mode=turn_input.memory_mode,
                active_character_names=turn_input.active_character_names,
                session_id=turn_input.session_id,
                save_repo=eff_save_repo,
                include_self_public=True,
            )
            for repo, scope_filter in unbounded_targets:
                for hit in repo.search_candidates(
                    MemoryCandidateQuery(
                        scope_filter=scope_filter,
                        query_vectors=q_vecs,
                        keyword_query=plan.keyword_query,
                        limit=candidate_limit,
                    )
                ):
                    collected[(id(repo), hit.record.id)] = (repo, hit, False, False, False)

        # On >4h session wakeup, proactively surface dynamic promises / high-importance recent items
        # (never seed static canon lore without genuine query relevance).
        if plan.is_session_wakeup:
            wakeup_targets = self._build_read_targets(
                memory_mode=turn_input.memory_mode,
                active_character_names=turn_input.active_character_names,
                session_id=turn_input.session_id,
                save_repo=eff_save_repo,
                include_self_public=True,
            )
            for repo, scope_filter in wakeup_targets:
                for rec in repo.list_by_scope(scope_filter, limit=8):
                    if _is_canon_memory(rec):
                        continue
                    key = (id(repo), rec.id)
                    if key in collected:
                        existing_repo, existing_hit, is_temp, _is_hop, _ = collected[key]
                        if rec.kind == "promise" or rec.importance >= 0.75:
                            collected[key] = (existing_repo, existing_hit, is_temp, False, True)
                        continue
                    if rec.kind == "promise" or rec.importance >= 0.75:
                        collected[key] = (
                            repo,
                            CandidateHit(record=rec, vector_score=0.0, fts_score=0.0),
                            False,
                            False,
                            True,
                        )

        # 1-hop entity expansion strictly within the exact same scope filters (zero telepathy!)
        seed_entities: list[str] = []
        for _repo, hit, is_temp, _is_hop, _is_wake in collected.values():
            if (
                hit.vector_score >= 0.42
                or hit.fts_score >= 0.50
                or is_temp
            ) and hit.record.entities:
                seed_entities.extend(hit.record.entities)
        dedup_entities = tuple(dict.fromkeys(e for e in seed_entities if e))
        if dedup_entities:
            hop_targets = self._build_read_targets(
                memory_mode=turn_input.memory_mode,
                active_character_names=turn_input.active_character_names,
                session_id=turn_input.session_id,
                save_repo=eff_save_repo,
                include_self_public=True,
            )
            for repo, scope_filter in hop_targets:
                for hop_rec in repo.expand_entities(dedup_entities, scope_filter, limit=6):
                    key = (id(repo), hop_rec.id)
                    if key in collected:
                        ex_repo, ex_hit, ex_temp, _ex_hop, ex_wake = collected[key]
                        collected[key] = (ex_repo, ex_hit, ex_temp, True, ex_wake)
                    else:
                        hop_vec_score = _max_cosine_against_queries(hop_rec.embedding, q_vecs)
                        collected[key] = (
                            repo,
                            CandidateHit(
                                record=hop_rec,
                                vector_score=hop_vec_score,
                                fts_score=0.0,
                            ),
                            False,
                            True,
                            False,
                        )

        active_scored: list[_ScoredCandidate] = []
        dormant_scored: list[_ScoredCandidate] = []
        sid = str(turn_input.session_id or "").strip()
        offline_gap = float(turn_input.seconds_since_last_turn or 0.0)

        for repo, hit, is_temporal_hit, is_entity_hop, is_wakeup_seed in collected.values():
            rec = hit.record
            if rec.superseded_by is not None:
                continue
            if rec.id in turn_input.recently_injected_ids:
                continue
            if (
                sid
                and rec.source_session_id == sid
                and rec.source_turn_seq is not None
                and int(rec.source_turn_seq) in turn_input.in_window_turn_seqs
            ):
                continue

            ret_state = self._evaluate_retention(
                rec,
                now_ts=now_ts,
                offline_gap_seconds=offline_gap,
            )
            is_canon = _is_canon_memory(rec, ret_state)

            fts_equiv = min(1.0, float(hit.fts_score) * 1.15)
            raw_relevance = max(float(hit.vector_score), fts_equiv)
            relevance = raw_relevance
            if not is_canon:
                if is_temporal_hit:
                    relevance = max(relevance + 0.22, 0.45)
                if is_wakeup_seed:
                    relevance = max(relevance, 0.56)
                if is_entity_hop:
                    relevance = max(relevance, 0.44)
            elif is_temporal_hit and raw_relevance > 0.0:
                relevance = min(1.0, raw_relevance + 0.15)

            final_score = (
                0.65 * min(1.0, max(0.0, relevance))
                + 0.25 * ret_state.retention
                + 0.10 * max(0.0, min(1.0, float(rec.importance)))
            )

            if ret_state.tier == "dormant":
                can_awaken = (
                    hit.vector_score >= self.dormant_awaken_vector_sim
                    or hit.fts_score >= self.dormant_awaken_fts_score
                    or (hit.fts_score >= 0.65 and hit.vector_score >= 0.50)
                    or (
                        is_temporal_hit
                        and (hit.vector_score >= 0.48 or hit.fts_score >= 0.50)
                    )
                )
                if can_awaken:
                    dormant_scored.append(
                        _ScoredCandidate(
                            repo=repo,
                            record=rec,
                            retention_state=ret_state,
                            vector_score=hit.vector_score,
                            fts_score=hit.fts_score,
                            relevance=relevance,
                            final_score=final_score,
                            awakened_dormant=True,
                        )
                    )
                continue

            if is_canon:
                if relevance < self.canon_min_relevance or final_score < self.canon_min_score:
                    continue
            elif relevance < self.min_relevance:
                continue

            active_scored.append(
                _ScoredCandidate(
                    repo=repo,
                    record=rec,
                    retention_state=ret_state,
                    vector_score=hit.vector_score,
                    fts_score=hit.fts_score,
                    relevance=relevance,
                    final_score=final_score,
                    awakened_dormant=False,
                )
            )

        active_scored.sort(
            key=lambda c: (c.final_score, c.relevance, c.record.created_at),
            reverse=True,
        )
        dormant_scored.sort(
            key=lambda c: (c.relevance, c.final_score, c.record.created_at),
            reverse=True,
        )

        selected: list[_ScoredCandidate] = []
        seen_slots: set[tuple[str, str]] = set()
        seen_texts: set[str] = set()
        max_total = max(1, int(plan.limit))

        for item in active_scored:
            if len(selected) >= max_total:
                break
            if item.record.slot_key:
                slot_pair = (item.record.owner_id.casefold(), item.record.slot_key.casefold())
                if slot_pair in seen_slots:
                    continue
                seen_slots.add(slot_pair)
            norm_text = " ".join(item.record.detail_text.casefold().split())
            if norm_text in seen_texts:
                continue
            seen_texts.add(norm_text)
            selected.append(item)

        awakened_count = 0
        for item in dormant_scored:
            if awakened_count >= self.max_dormant_awakened or len(selected) >= max_total:
                break
            if item.record.slot_key:
                slot_pair = (item.record.owner_id.casefold(), item.record.slot_key.casefold())
                if slot_pair in seen_slots:
                    continue
                seen_slots.add(slot_pair)
            norm_text = " ".join(item.record.detail_text.casefold().split())
            if norm_text in seen_texts:
                continue
            seen_texts.add(norm_text)
            selected.append(item)
            awakened_count += 1

        if not selected:
            return MemoryContextBlock(rendered="", recalled_ids=())

        by_repo: dict[int, tuple[MemoryRepository, list[str]]] = {}
        for item in selected:
            rid = id(item.repo)
            if rid not in by_repo:
                by_repo[rid] = (item.repo, [])
            by_repo[rid][1].append(item.record.id)
        for repo_obj, ids in by_repo.values():
            repo_obj.record_recall(ids, recalled_at=now_ts)

        multi_char = len(normalize_character_owners(turn_input.active_character_names)) > 1
        bullet_lines: list[str] = []
        recalled_ids: list[str] = []
        for item in selected:
            recalled_ids.append(item.record.id)
            owner_prefix = ""
            if multi_char and item.record.owner_id not in {"__self__", "user", ""}:
                owner_prefix = f"（{item.record.owner_id}）"
            bullet_lines.append(f"- {owner_prefix}{item.retention_state.rendered_text}")

        rendered = (
            f"{INJECTION_HEADER}\n"
            "Relevant long-term memories for this turn. Respect each item's clarity tag "
            "([固有设定], [清晰], [较久远·印象模糊], [唤醒的久远记忆]); use them naturally as background "
            "and never mention the retrieval system unless asked.\n"
            + "\n".join(bullet_lines)
        )
        return MemoryContextBlock(
            rendered=rendered,
            recalled_ids=tuple(recalled_ids),
        )

    def search_for_tool(
        self,
        query: str,
        *,
        character_name: str = "user",
        session_id: str = "",
        memory_mode: str = MEMORY_MODE_SHARED,
        save_repo: MemoryRepository | None = None,
        now_ts: float | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Deep hybrid search for the `memory_search` tool (can awaken dormant memories)."""
        q = str(query or "").strip()
        if not q:
            return []
        eff_now = float(now_ts) if now_ts is not None and now_ts > 0 else time.time()
        eff_save = self._effective_save_repo(save_repo)
        bounded_limit = max(1, int(limit))
        agent = str(character_name or "user").strip()
        is_self = agent.casefold() in _SELF_OWNER_ALIASES

        plan = self.recall_planner.plan(
            TurnRecallInput(
                user_text=q,
                active_character_names=() if is_self else (agent,),
                session_id=session_id,
                memory_mode=memory_mode,
                now_ts=eff_now,
            )
        )
        clauses = plan.query_clauses if plan.query_clauses else (q,)
        mat = self.embedder.embed_documents(list(clauses))
        q_vecs = tuple(mat[i] for i in range(len(clauses)))

        targets = self._build_read_targets(
            memory_mode=memory_mode,
            active_character_names=() if is_self else (agent,),
            session_id=session_id,
            save_repo=eff_save,
            include_self_public=True,
            event_from=plan.event_from,
            event_to=plan.event_to,
        )
        raw_hits: dict[tuple[int, str], tuple[MemoryRepository, CandidateHit]] = {}
        for repo, scope_filter in targets:
            for hit in repo.search_candidates(
                MemoryCandidateQuery(
                    scope_filter=scope_filter,
                    query_vectors=q_vecs,
                    keyword_query=q,
                    limit=max(bounded_limit * 3, 20),
                )
            ):
                raw_hits[(id(repo), hit.record.id)] = (repo, hit)

        if (plan.event_from is not None or plan.event_to is not None) and not raw_hits:
            for repo, scope_filter in self._build_read_targets(
                memory_mode=memory_mode,
                active_character_names=() if is_self else (agent,),
                session_id=session_id,
                save_repo=eff_save,
                include_self_public=True,
            ):
                for hit in repo.search_candidates(
                    MemoryCandidateQuery(
                        scope_filter=scope_filter,
                        query_vectors=q_vecs,
                        keyword_query=q,
                        limit=max(bounded_limit * 3, 20),
                    )
                ):
                    raw_hits[(id(repo), hit.record.id)] = (repo, hit)

        rows: list[tuple[float, MemoryRepository, MemoryRecord, RetentionState, float]] = []
        for repo, hit in raw_hits.values():
            rec = hit.record
            if rec.superseded_by is not None:
                continue
            ret_state = self._evaluate_retention(rec, now_ts=eff_now)
            raw_score = max(
                0.0,
                min(
                    1.0,
                    max(float(hit.vector_score), float(hit.fts_score)),
                ),
            )
            if _is_canon_memory(rec, ret_state):
                canon_relevance = max(
                    float(hit.vector_score),
                    min(1.0, float(hit.fts_score) * 1.15),
                )
                canon_final = (
                    0.65 * min(1.0, max(0.0, canon_relevance))
                    + 0.25 * ret_state.retention
                    + 0.10 * max(0.0, min(1.0, float(rec.importance)))
                )
                if (
                    canon_relevance < self.canon_min_relevance
                    or canon_final < self.canon_min_score
                ):
                    continue
            # Active tool search uses a gentler awakening bar than passive before_chat
            if (
                ret_state.tier == "dormant"
                and hit.vector_score < 0.55
                and hit.fts_score < 0.50
                and plan.event_from is None
            ):
                continue
            rank = 0.75 * max(hit.vector_score, hit.fts_score) + 0.25 * ret_state.retention
            rows.append((rank, repo, rec, ret_state, raw_score))

        rows.sort(key=lambda item: (item[0], item[4], item[2].created_at), reverse=True)
        chosen = rows[:bounded_limit]

        by_repo: dict[int, tuple[MemoryRepository, list[str]]] = {}
        out: list[dict[str, Any]] = []
        for _rank, repo, rec, ret_state, raw_score in chosen:
            rid = id(repo)
            if rid not in by_repo:
                by_repo[rid] = (repo, [])
            by_repo[rid][1].append(rec.id)
            memory_text = (
                rec.detail_text
                if ret_state.tier in {"canon", "clear"}
                else (rec.gist_text or rec.detail_text)
            )
            out.append(
                {
                    "id": rec.id,
                    "memory": memory_text,
                    "detail": rec.detail_text,
                    "gist": rec.gist_text or rec.detail_text,
                    "clarity": ret_state.tier,
                    "retention": round(ret_state.retention, 4),
                    "rendered": ret_state.rendered_text,
                    "score": raw_score,
                }
            )
        for repo_obj, ids in by_repo.values():
            repo_obj.record_recall(ids, recalled_at=eff_now)
        return out

    def ingest_drafts(
        self,
        drafts: Sequence[MemoryDraft],
        *,
        memory_mode: str = MEMORY_MODE_SHARED,
        save_repo: MemoryRepository | None = None,
        player_character: str = "",
        now_ts: float | None = None,
        dedupe_threshold: float | None = None,
    ) -> IngestReport:
        """Batch-embed, deduplicate, supersede `slot_key` conflicts, and persist drafts."""
        valid_drafts = [d for d in drafts if str(d.detail_text or "").strip()]
        if not valid_drafts:
            return IngestReport()

        eff_now = float(now_ts) if now_ts is not None and now_ts > 0 else time.time()
        threshold = (
            float(dedupe_threshold)
            if dedupe_threshold is not None
            else semantic_deduplication_threshold()
        )
        texts = [str(d.detail_text).strip() for d in valid_drafts]
        embeddings = self.embedder.embed_documents(texts)

        added_ids: list[str] = []
        superseded_ids: list[str] = []
        skipped_duplicates = 0

        for idx, draft in enumerate(valid_drafts):
            detail = texts[idx]
            gist = str(draft.gist_text or "").strip() or detail
            slot_key = str(draft.slot_key or "").strip()
            vec = embeddings[idx]
            target_repo, scope, owner_id = self.resolve_write_target(
                draft,
                memory_mode=memory_mode,
                save_repo=save_repo,
                player_character=player_character,
            )

            read_filter = MemoryScopeFilter(
                scopes=(scope,),
                owner_ids=(owner_id,),
                session_id=(
                    str(draft.source_session_id or "").strip() or None
                    if scope == SCOPE_SAVE_ISOLATED and draft.source_session_id
                    else None
                ),
            )

            if slot_key:
                existing_slot_records = [
                    rec
                    for rec in target_repo.list_by_scope(read_filter, limit=50)
                    if rec.slot_key == slot_key and rec.superseded_by is None
                ]
                # Skip no-op rewrite if the active slot already has identical detail_text
                if any(
                    " ".join(rec.detail_text.casefold().split())
                    == " ".join(detail.casefold().split())
                    for rec in existing_slot_records
                ):
                    skipped_duplicates += 1
                    continue
                prior_ids = [rec.id for rec in existing_slot_records]
            else:
                prior_ids = []
                cand_hits = target_repo.search_candidates(
                    MemoryCandidateQuery(
                        scope_filter=read_filter,
                        query_vectors=(vec,),
                        keyword_query=detail,
                        limit=5,
                    )
                )
                candidates = [
                    {
                        "id": hit.record.id,
                        "memory": hit.record.detail_text,
                        "score": max(0.0, min(1.0, float(hit.vector_score))),
                    }
                    for hit in cand_hits
                ]
                dup = find_duplicate_memory(detail, candidates, threshold=threshold)
                if dup is not None:
                    skipped_duplicates += 1
                    continue

            new_id = target_repo.upsert(
                MemoryRecord(
                    id="",
                    scope=scope,
                    owner_id=owner_id,
                    detail_text=detail,
                    gist_text=gist,
                    slot_key=slot_key,
                    kind=str(draft.kind or "episodic").strip() or "episodic",
                    topic_tags=tuple(draft.topic_tags),
                    entities=tuple(draft.entities),
                    importance=float(max(0.0, min(1.0, float(draft.importance)))),
                    pinned=bool(draft.pinned or scope == SCOPE_CHAR_CANON or draft.kind == "canon"),
                    created_at=eff_now,
                    event_at=draft.event_at,
                    last_recalled_at=eff_now,
                    source_session_id=str(draft.source_session_id or "").strip(),
                    source_turn_seq=(
                        None if draft.source_turn_seq is None else int(draft.source_turn_seq)
                    ),
                    embedding=vec,
                )
            )
            added_ids.append(new_id)
            superseded_ids.extend(prior_ids)

        return IngestReport(
            added_ids=tuple(added_ids),
            superseded_ids=tuple(dict.fromkeys(superseded_ids)),
            skipped_duplicates=skipped_duplicates,
        )


__all__ = [
    "DEFAULT_CANON_MIN_RELEVANCE",
    "DEFAULT_CANON_MIN_SCORE",
    "DEFAULT_DORMANT_AWAKEN_FTS_SCORE",
    "DEFAULT_DORMANT_AWAKEN_VECTOR_SIM",
    "DEFAULT_MAX_DORMANT_AWAKENED",
    "DEFAULT_MIN_RELEVANCE",
    "INJECTION_HEADER",
    "MemoryOrchestrator",
    "is_roleplay_player_persona",
    "normalize_character_owners",
]

"""Ebbinghaus dual-granularity retention engine implementing RetentionPolicy."""

from __future__ import annotations

from collections.abc import Mapping
import math
import time

from ai.memory.temporal import format_event_date_tag
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    ClarityTier,
    MemoryRecord,
    RetentionState,
)

SECONDS_PER_DAY = 86_400.0
DEFAULT_CLEAR_THRESHOLD = 0.50
DEFAULT_FADED_THRESHOLD = 0.15
DEFAULT_MAX_OFFLINE_GAP_SECONDS = 7.0 * SECONDS_PER_DAY

DEFAULT_KIND_BASE_DAYS: dict[str, float] = {
    "episodic": 4.5,
    "promise": 8.0,
    "profile": 14.0,
    "canon": float("inf"),
}


class EbbinghausRetentionPolicy:
    """Evaluate memory decay R(t) = exp(-Delta_t_eff / S) and dual-granularity tier.

    Stability formula:
        S = S_0 * (1 + 0.6 * ln(1 + recall_count)) * (0.4 + 2.6 * importance)

    Non-decaying records (`pinned=True`, `scope == "char_canon"`, or `kind == "canon"`)
    always evaluate to `(retention=1.0, tier="canon")`. Dormant memories (`R < 0.15`)
    are never physically deleted; they remain stored for high-similarity awakening.
    """

    def __init__(
        self,
        *,
        kind_base_days: Mapping[str, float] | None = None,
        clear_threshold: float = DEFAULT_CLEAR_THRESHOLD,
        faded_threshold: float = DEFAULT_FADED_THRESHOLD,
        max_offline_gap_seconds: float = DEFAULT_MAX_OFFLINE_GAP_SECONDS,
    ) -> None:
        merged = dict(DEFAULT_KIND_BASE_DAYS)
        if kind_base_days:
            for key, days in kind_base_days.items():
                merged[str(key).strip().lower()] = float(days)
        self._kind_base_days = merged
        self.clear_threshold = float(clear_threshold)
        self.faded_threshold = float(faded_threshold)
        self.max_offline_gap_seconds = max(0.0, float(max_offline_gap_seconds))

    def stability_seconds(self, record: MemoryRecord) -> float:
        """Compute stability S (in seconds) from kind, recall_count, and importance."""
        if record.pinned or record.scope == SCOPE_CHAR_CANON or record.kind == "canon":
            return float("inf")
        kind_key = str(record.kind or "episodic").strip().lower()
        base_days = self._kind_base_days.get(kind_key, self._kind_base_days["episodic"])
        if math.isinf(base_days):
            return float("inf")
        s0 = max(0.25, float(base_days)) * SECONDS_PER_DAY
        n_recall = max(0, int(record.recall_count or 0))
        importance = max(0.0, min(1.0, float(record.importance)))
        recall_factor = 1.0 + 0.6 * math.log1p(n_recall)
        importance_factor = 0.4 + 2.6 * importance
        return s0 * recall_factor * importance_factor

    def effective_elapsed_seconds(
        self,
        record: MemoryRecord,
        *,
        now_ts: float,
        offline_gap_seconds: float = 0.0,
    ) -> float:
        """Compute elapsed decay time, discounting single-session idle gaps beyond 7 days."""
        anchor_ts = max(
            float(record.created_at or 0.0),
            float(record.last_recalled_at or 0.0),
        )
        if anchor_ts <= 0.0:
            return 0.0
        raw_elapsed = max(0.0, float(now_ts) - anchor_ts)
        gap = max(0.0, float(offline_gap_seconds or 0.0))
        if self.max_offline_gap_seconds > 0.0 and gap > self.max_offline_gap_seconds:
            applicable_gap = min(raw_elapsed, gap)
            if applicable_gap > self.max_offline_gap_seconds:
                excess_idle = applicable_gap - self.max_offline_gap_seconds
                return max(0.0, raw_elapsed - excess_idle)
        return raw_elapsed

    def evaluate(
        self,
        record: MemoryRecord,
        *,
        now_ts: float = 0.0,
        offline_gap_seconds: float = 0.0,
    ) -> RetentionState:
        """Evaluate retention score and format dual-granularity presentation text."""
        effective_now = float(now_ts) if now_ts > 0.0 else time.time()
        date_tag = format_event_date_tag(record.event_at, now_ts=effective_now)
        date_suffix = f"·{date_tag}" if date_tag else ""
        detail = str(record.detail_text or "").strip()
        gist = str(record.gist_text or "").strip() or detail

        if record.pinned or record.scope == SCOPE_CHAR_CANON or record.kind == "canon":
            return RetentionState(
                retention=1.0,
                tier="canon",
                rendered_text=f"[固有设定{date_suffix}] {detail}",
            )

        stability = self.stability_seconds(record)
        if math.isinf(stability) or stability <= 0.0:
            retention = 1.0
        else:
            elapsed = self.effective_elapsed_seconds(
                record,
                now_ts=effective_now,
                offline_gap_seconds=offline_gap_seconds,
            )
            retention = math.exp(-elapsed / stability)
            retention = max(0.0, min(1.0, retention))

        tier: ClarityTier
        if retention >= self.clear_threshold:
            tier = "clear"
            rendered = f"[清晰{date_suffix}] {detail}"
        elif retention >= self.faded_threshold:
            tier = "faded"
            rendered = f"[较久远·印象模糊{date_suffix}] {gist}"
        else:
            tier = "dormant"
            rendered = f"[唤醒的久远记忆{date_suffix}] {gist}"

        return RetentionState(
            retention=retention,
            tier=tier,
            rendered_text=rendered,
        )


__all__ = [
    "DEFAULT_CLEAR_THRESHOLD",
    "DEFAULT_FADED_THRESHOLD",
    "DEFAULT_KIND_BASE_DAYS",
    "DEFAULT_MAX_OFFLINE_GAP_SECONDS",
    "EbbinghausRetentionPolicy",
    "SECONDS_PER_DAY",
]

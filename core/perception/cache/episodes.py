"""Dual-stage episodic archiving (`总体纪要` + `分钟划分纪要`) for Vision Memory."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import re

from core.perception.cache.tracks import observation_key
from core.perception.models import VisionEpisode, normalize_scene_mood


def build_fallback_episode_summary(
    batch: list[tuple[float, str, str]],
    *,
    max_chars: int = 120,
) -> str:
    """Deterministic compact fallback (字幕 -> 画面) when Cloud LLM summarization is unavailable."""
    visuals: list[str] = []
    subtitles: list[str] = []
    for _ts, kind, text in batch:
        clean = str(text or "").strip().rstrip("。；;，,！!？?")
        if not clean:
            continue
        target = visuals if kind == "画面" else subtitles
        if not target or observation_key(clean) != observation_key(target[-1]):
            target.append(clean)
    parts: list[str] = []
    if subtitles:
        sub_clause = "，".join(subtitles[:2])[:46].rstrip(" ，,；;。")
        parts.append(f"字幕：{sub_clause}。")
    if visuals:
        vis_clause = "，".join(visuals[:2])[:44].rstrip(" ，,；;。")
        parts.append(f"画面：{vis_clause}。")
    if not parts:
        return ""
    limit = max(30, int(max_chars))
    joined = "".join(parts)
    if len(joined) <= limit:
        return joined
    return joined[: limit - 1].rstrip(" ，,、：:。；;") + "。"


def merge_fallback_overall_summary(
    previous_overall: str,
    minute_summary: str,
    *,
    max_chars: int = 180,
) -> str:
    """Roll a new minute-slice summary into the overall summary deterministically."""
    prev = str(previous_overall or "").strip().rstrip("。；; ")
    curr = str(minute_summary or "").strip().rstrip("。；; ")
    limit = max(60, int(max_chars))
    if not curr:
        return prev[:limit]
    if not prev:
        return curr[:limit]
    if observation_key(curr) in observation_key(prev):
        return prev[:limit]
    combined = f"{prev}；{curr}"
    if len(combined) <= limit:
        return combined
    clauses = [c.strip() for c in re.split(r"[；;。]+", combined) if c.strip()]
    while len(clauses) > 1 and len("；".join(clauses)) > limit:
        clauses.pop(0)
    merged = "；".join(clauses)
    return merged[-limit:].lstrip("；;，, ") if len(merged) > limit else merged


class EpisodeArchive:
    """Staging buffer, rolling `overall_summary`, and `VisionEpisode` minute-slice chapters."""

    def __init__(self, *, max_episodes: int, batch_size: int) -> None:
        self.max_episodes = max(2, int(max_episodes))
        self.batch_size = max(4, int(batch_size))
        self.staging: deque[tuple[float, str, str]] = deque(maxlen=128)
        self.episodes: deque[VisionEpisode] = deque(maxlen=self.max_episodes)
        self.overall_summary: str = ""
        self.last_summary_at: float = 0.0
        self._counter: int = 0

    def stage(self, timestamp: float, kind: str, text: str) -> None:
        clean = str(text or "").strip()
        if not clean:
            return
        if self.staging:
            prev_ts, prev_kind, prev_text = self.staging[-1]
            if prev_kind == kind and observation_key(prev_text) == observation_key(clean):
                self.staging[-1] = (max(prev_ts, timestamp), kind, clean)
                return
        self.staging.append((timestamp, kind, clean))

    def needs_compaction(self, *, min_items: int | None = None) -> bool:
        threshold = self.batch_size if min_items is None else max(2, int(min_items))
        return len(self.staging) >= threshold

    def is_interval_due(
        self,
        *,
        now: float,
        interval_sec: float,
        min_items: int = 2,
    ) -> bool:
        if len(self.staging) >= self.batch_size:
            return True
        if len(self.staging) < max(1, int(min_items)):
            return False
        oldest_ts = min(ts for ts, _kind, _text in self.staging)
        anchor = self.last_summary_at if self.last_summary_at > 0.0 else oldest_ts
        return (now - anchor) >= max(30.0, float(interval_sec))

    def pop_due_batch(
        self,
        *,
        now: float,
        interval_sec: float,
        min_items: int = 2,
        max_items: int = 36,
        force: bool = False,
    ) -> list[tuple[float, str, str]]:
        if not self.staging:
            return []
        if not force and not self.is_interval_due(
            now=now,
            interval_sec=interval_sec,
            min_items=min_items,
        ):
            return []
        count = min(len(self.staging), max(1, int(max_items)))
        batch = [self.staging.popleft() for _ in range(count)]
        batch.sort(key=lambda item: item[0])
        self.last_summary_at = now
        return batch

    def pop_batch(
        self,
        *,
        min_items: int | None = None,
        max_items: int = 20,
        force: bool = False,
    ) -> list[tuple[float, str, str]]:
        threshold = 2 if force else (self.batch_size if min_items is None else max(2, int(min_items)))
        if len(self.staging) < threshold:
            return []
        count = min(len(self.staging), max(2, int(max_items)))
        batch = [self.staging.popleft() for _ in range(count)]
        batch.sort(key=lambda item: item[0])
        return batch

    def append(
        self,
        summary: str,
        *,
        start_ts: float,
        end_ts: float,
        mood: str,
        alloc_seq: Callable[[], int],
        overall_summary: str | None = None,
        minute_max_chars: int = 140,
        overall_max_chars: int = 180,
    ) -> VisionEpisode | None:
        clean = str(summary or "").strip()[: max(30, int(minute_max_chars))]
        if not clean:
            return None
        self._counter += 1
        episode = VisionEpisode(
            index=self._counter,
            start_ts=start_ts,
            end_ts=max(start_ts, end_ts),
            summary=clean,
            mood=normalize_scene_mood(mood) or "unclear",
        )
        self.episodes.append(episode)
        if overall_summary is not None:
            clean_overall = str(overall_summary).strip()[: max(60, int(overall_max_chars))]
            if clean_overall:
                self.overall_summary = clean_overall
        self.last_summary_at = max(self.last_summary_at, end_ts)
        alloc_seq()
        return episode

    def record_dual_summary(
        self,
        *,
        minute_summary: str,
        overall_summary: str,
        start_ts: float,
        end_ts: float,
        mood: str,
        minute_max_chars: int = 120,
        overall_max_chars: int = 180,
        alloc_seq: Callable[[], int],
    ) -> VisionEpisode | None:
        clean_minute = str(minute_summary or "").strip()[: max(30, int(minute_max_chars))]
        resolved_overall = (
            str(overall_summary or "").strip()[: max(60, int(overall_max_chars))]
            or merge_fallback_overall_summary(
                self.overall_summary,
                clean_minute,
                max_chars=overall_max_chars,
            )
        )
        return self.append(
            clean_minute,
            start_ts=start_ts,
            end_ts=end_ts,
            mood=mood,
            alloc_seq=alloc_seq,
            overall_summary=resolved_overall,
            minute_max_chars=minute_max_chars,
            overall_max_chars=overall_max_chars,
        )

    def clear(self) -> None:
        self.staging.clear()
        self.episodes.clear()
        self.overall_summary = ""
        self.last_summary_at = 0.0
        self._counter = 0

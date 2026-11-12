"""Episodic chapter archiving for evicted working-window items."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from core.perception.cache.tracks import observation_key
from core.perception.models import VisionEpisode, normalize_scene_mood


def build_fallback_episode_summary(batch: list[tuple[float, str, str]]) -> str:
    """Deterministic compact fallback when local VLM text summarization is unavailable."""
    visuals: list[str] = []
    subtitles: list[str] = []
    for _ts, kind, text in batch:
        clean = str(text or "").strip().rstrip("。；;，,")
        if not clean:
            continue
        target = visuals if kind == "画面" else subtitles
        if not target or observation_key(clean) != observation_key(target[-1]):
            target.append(clean)
    parts: list[str] = []
    if visuals:
        parts.append("画面：" + " → ".join(visuals[:2])[:56])
    if subtitles:
        parts.append("台词提及：" + " / ".join(subtitles[:3])[:72])
    return "；".join(parts)[:140]


class EpisodeArchive:
    """Staging buffer and immutable `VisionEpisode` chapter list (~20-25 min session memory)."""

    def __init__(self, *, max_episodes: int, batch_size: int) -> None:
        self.max_episodes = max(2, int(max_episodes))
        self.batch_size = max(4, int(batch_size))
        self.staging: deque[tuple[float, str, str]] = deque(maxlen=96)
        self.episodes: deque[VisionEpisode] = deque(maxlen=self.max_episodes)
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
        threshold = self.batch_size if min_items is None else max(4, int(min_items))
        return len(self.staging) >= threshold

    def pop_batch(
        self,
        *,
        min_items: int | None = None,
        max_items: int = 20,
        force: bool = False,
    ) -> list[tuple[float, str, str]]:
        threshold = 4 if force else (self.batch_size if min_items is None else max(4, int(min_items)))
        if len(self.staging) < threshold:
            return []
        count = min(len(self.staging), max(4, int(max_items)))
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
    ) -> VisionEpisode | None:
        clean = str(summary or "").strip()[:180]
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
        alloc_seq()
        return episode

    def clear(self) -> None:
        self.staging.clear()
        self.episodes.clear()
        self._counter = 0

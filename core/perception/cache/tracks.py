"""Visual and chronological subtitle tracks for Tier-1 Vision Memory."""

from __future__ import annotations

from collections.abc import Callable
from difflib import SequenceMatcher
import re
from unicodedata import normalize

from core.perception.models import SubtitleItem, VisualBeat

_QUOTED_SUBTITLE_RE = re.compile(
    r"(?:画面|屏幕)?(?:下方|底部|上方)?的?有?字幕"
    r"(?:显示|写着|写道|是|为)?[：:\s]*[“「『\"‘'][^”」』\"’'\n]+[”」』\"’']"
)
_SUBTITLE_CLAUSE_PREFIX_RE = re.compile(
    r"^(?:画面|屏幕)?(?:下方|底部|上方)?的?有?字幕(?:显示|写着|写道|是|为)"
)
_LEADING_VISUAL_PREFIX_RE = re.compile(
    r"^(?:当前|右侧|右边)(?:的)?画面(?:中|里)?(?:显示|为|是)?[：:\s]*"
)
_CLAUSE_SPLIT_RE = re.compile(r"([^，,。；;！？!?\n]+)([，,。；;！？!?\n]*)")
_ASCII_DIGITS_RE = re.compile(r"\d+(?:\.\d+)?%?")


def observation_key(text: str) -> str:
    """Normalize text to casefolded alphanumeric characters for structural comparison."""
    return "".join(ch for ch in normalize("NFKC", str(text or "")).casefold() if ch.isalnum())


def digits_signature(text: str) -> tuple[str, ...]:
    """Extract numeric tokens so numeric changes (e.g. `90` -> `10`) are never merged."""
    return tuple(_ASCII_DIGITS_RE.findall(normalize("NFKC", str(text or ""))))


def is_near_identical(left: str, right: str, *, threshold: float = 0.90) -> bool:
    """Return True only when two observations are structurally identical or 1-char jitter."""
    left_key = observation_key(left)
    right_key = observation_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if digits_signature(left) != digits_signature(right):
        return False
    return (
        min(len(left_key), len(right_key)) >= 6
        and SequenceMatcher(None, left_key, right_key).ratio() >= threshold
    )


def is_ambient_reaction_bark(bark: str) -> bool:
    """Return True for silent ellipses or `（看着……）` ambient bubbles that aren't spoken lines."""
    clean = str(bark or "").strip()
    if not clean or clean in {"……", "...", "…", "……！", "……？"}:
        return True
    return (clean.startswith("（") and clean.endswith("）")) or (
        clean.startswith("(") and clean.endswith(")")
    )


def clean_visual_summary(text: str, subtitle_keys: set[str]) -> str:
    """Strip clauses that merely transcribe an OCR subtitle already tracked on the subtitle track."""
    stripped = _QUOTED_SUBTITLE_RE.sub("", str(text or ""))
    whole_key = observation_key(stripped)
    if not whole_key or whole_key in subtitle_keys:
        return ""
    kept: list[str] = []
    for clause, sep in _CLAUSE_SPLIT_RE.findall(stripped):
        clean_clause = _LEADING_VISUAL_PREFIX_RE.sub("", clause.strip())
        key = observation_key(clean_clause)
        if not key or _SUBTITLE_CLAUSE_PREFIX_RE.match(clean_clause):
            continue
        if key in subtitle_keys or (
            len(key) >= 6
            and any(
                key in sub or (sub in key and len(key) - len(sub) <= 5)
                for sub in subtitle_keys
            )
        ):
            continue
        kept.append(clean_clause + sep)
    return "".join(kept).strip(" ，,；;\n")


class SubtitleTrack:
    """Chronological OCR subtitle buffer with typewriter expansion merging."""

    def __init__(self, *, max_items: int) -> None:
        self.max_items = max(4, int(max_items))
        self.items: list[SubtitleItem] = []
        self.last_raw_text: str = ""

    def subtitle_keys(self, *, recent: int = 12) -> set[str]:
        return {
            key
            for item in self.items[-recent:]
            if len(key := observation_key(item.text)) >= 4
        }

    def record_text(
        self,
        raw_text: str,
        *,
        captured_at: float,
        alloc_seq: Callable[[], int],
        on_evict: Callable[[float, str, str], None],
    ) -> None:
        trimmed = str(raw_text or "").strip()[:320]
        if not trimmed:
            self.last_raw_text = ""
            return
        if trimmed == self.last_raw_text and self.items:
            return
        self.last_raw_text = trimmed
        for raw_line in trimmed.splitlines():
            line = raw_line.strip()
            if line:
                self._insert_line(
                    line,
                    captured_at=captured_at,
                    alloc_seq=alloc_seq,
                    on_evict=on_evict,
                )

    def _insert_line(
        self,
        line: str,
        *,
        captured_at: float,
        alloc_seq: Callable[[], int],
        on_evict: Callable[[float, str, str], None],
    ) -> None:
        clean = line[:180]
        key = observation_key(clean)
        if not key:
            return
        digits = digits_signature(clean)

        for item in reversed(self.items[-4:]):
            dt = abs(captured_at - item.timestamp)
            item_key = observation_key(item.text)
            if key == item_key:
                item.timestamp = max(item.timestamp, captured_at)
                return
            if dt <= 4.5 and digits == digits_signature(item.text):
                # Typewriter prefix/substring expansion of the same subtitle
                if len(item_key) >= 3 and item_key in key:
                    item.text = clean
                    item.timestamp = max(item.timestamp, captured_at)
                    item.seq = alloc_seq()
                    return
                if len(key) >= 3 and key in item_key and captured_at >= item.timestamp:
                    return
                if dt <= 3.5 and is_near_identical(item.text, clean, threshold=0.90):
                    if len(clean) >= len(item.text):
                        item.text = clean
                    item.timestamp = max(item.timestamp, captured_at)
                    return

        entry = SubtitleItem(seq=alloc_seq(), timestamp=captured_at, text=clean)
        self.items.append(entry)
        if len(self.items) >= 2 and self.items[-2].timestamp > entry.timestamp:
            self.items.sort(key=lambda s: (s.timestamp, s.seq))
        while len(self.items) > self.max_items:
            evicted = self.items.pop(0)
            on_evict(evicted.timestamp, "字幕", evicted.text)

    def recent_lines(self, *, now: float, limit: int = 4, max_age_sec: float = 45.0) -> list[str]:
        cutoff = now - max_age_sec if max_age_sec > 0 else 0.0
        matching = [item.text for item in self.items if item.timestamp >= cutoff]
        return matching[-max(1, int(limit)) :]

    def clear(self) -> None:
        self.items.clear()
        self.last_raw_text = ""


class VisualTrack:
    """Scene anchor + incremental `detail` / `cut` visual beats."""

    def __init__(self, *, max_beats: int) -> None:
        self.max_beats = max(2, int(max_beats))
        self.beats: list[VisualBeat] = []
        self.scene_anchor: str = ""
        self.scene_anchor_at: float = 0.0
        self.scene_anchor_seq: int = 0
        self.current_digest: str = ""
        self.current_digest_at: float = 0.0

    def record_visual(
        self,
        cleaned_visual: str,
        *,
        visual_change: str,
        salience: float,
        now: float,
        alloc_seq: Callable[[], int],
        on_evict: Callable[[float, str, str], None],
    ) -> None:
        if visual_change == "none" or not cleaned_visual:
            if self.scene_anchor and not cleaned_visual and visual_change == "none":
                self.scene_anchor_at = max(self.scene_anchor_at, now)
            return

        matched = next(
            (b for b in reversed(self.beats[-2:]) if is_near_identical(b.summary, cleaned_visual)),
            None,
        )
        if matched is not None:
            matched.timestamp = max(matched.timestamp, now)
            matched.salience = max(matched.salience, salience)
            self.current_digest = matched.summary
            self.current_digest_at = matched.timestamp
            if visual_change == "cut" or not self.scene_anchor:
                self.scene_anchor = matched.summary
                self.scene_anchor_at = matched.timestamp
            return

        if self.scene_anchor and is_near_identical(self.scene_anchor, cleaned_visual):
            self.scene_anchor_at = max(self.scene_anchor_at, now)
            self.current_digest = self.scene_anchor
            self.current_digest_at = self.scene_anchor_at
            return

        seq = alloc_seq()
        beat = VisualBeat(
            seq=seq,
            timestamp=now,
            kind=visual_change,
            summary=cleaned_visual,
            salience=salience,
        )
        self.beats.append(beat)
        if len(self.beats) >= 2 and self.beats[-2].timestamp > now:
            self.beats.sort(key=lambda b: (b.timestamp, b.seq))
        self.current_digest = cleaned_visual
        self.current_digest_at = now
        if visual_change == "cut" or not self.scene_anchor:
            self.scene_anchor = cleaned_visual
            self.scene_anchor_at = now
            self.scene_anchor_seq = seq
        while len(self.beats) > self.max_beats:
            evicted = self.beats.pop(0)
            on_evict(evicted.timestamp, "画面", evicted.summary)

    def clear(self) -> None:
        self.beats.clear()
        self.scene_anchor = ""
        self.scene_anchor_at = 0.0
        self.scene_anchor_seq = 0
        self.current_digest = ""
        self.current_digest_at = 0.0

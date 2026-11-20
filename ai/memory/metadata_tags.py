"""Codec for zero-schema-invasion system metadata carried in `topic_tags`.

Allows bi-temporal foresight TTL (`valid_until`), cross-slot conflict
superseding (`supersedes_ids`), multimodal raw evidence pointers (`visual_ref`),
and scene consolidation watermarks (`consolidated_seq`) to traverse all
existing SOLID `Protocol` ports, persistent queues, and HTTP bridges with
zero modifications to `sdk/adapters/memory.py` or SQLite table schemas.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math

SYS_TAG_NAMESPACE = "__sys:"
SYS_VALID_UNTIL_PREFIX = "__sys:valid_until:"
SYS_SUPERSEDES_PREFIX = "__sys:supersedes:"
SYS_VISUAL_REF_PREFIX = "__sys:visual_ref:"
SYS_CONSOLIDATED_SEQ_PREFIX = "__sys:consolidated_seq:"

_MAX_PUBLIC_TAGS = 12
_MAX_TAG_CHARS = 80
_MAX_SUPERSEDES = 16
_MAX_VISUAL_REF_CHARS = 512


@dataclass(frozen=True, slots=True)
class ParsedSystemMeta:
    """Decoded system metadata separated from user-visible `public_tags`."""

    public_tags: tuple[str, ...] = ()
    valid_until: float | None = None
    supersedes_ids: tuple[str, ...] = ()
    visual_ref: str = ""
    consolidated_seq: int | None = None


def is_system_tag(tag: str) -> bool:
    """Return True when `tag` uses the reserved `__sys:` metadata prefix."""
    return str(tag or "").strip().startswith(SYS_TAG_NAMESPACE)


def sanitize_visual_ref(raw_ref: str) -> str:
    """Normalize a relative visual evidence pointer and reject unsafe segments."""
    cleaned = str(raw_ref or "").strip().replace("\\", "/")
    if not cleaned or len(cleaned) > _MAX_VISUAL_REF_CHARS:
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return ""
    parts = [seg for seg in cleaned.split("/") if seg and seg != "."]
    if not parts or any(seg == ".." for seg in parts):
        return ""
    # Reject drive-letter or UNC absolute host paths; keep vault-relative refs only.
    if ":" in parts[0] or cleaned.startswith("//"):
        return ""
    return "/".join(parts)


def strip_system_tags(tags: Iterable[str] | None) -> tuple[str, ...]:
    """Return deduplicated user-facing `topic_tags` with all `__sys:*` tags removed."""
    if not tags:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        val = str(raw or "").strip()
        if not val or val.startswith(SYS_TAG_NAMESPACE):
            continue
        if len(val) > _MAX_TAG_CHARS:
            val = val[:_MAX_TAG_CHARS].rstrip()
        key = val.casefold()
        if key not in seen:
            seen.add(key)
            out.append(val)
        if len(out) >= _MAX_PUBLIC_TAGS:
            break
    return tuple(out)


def unpack_system_tags(tags: Iterable[str] | None) -> ParsedSystemMeta:
    """Decode `topic_tags` into user-visible tags and structured system metadata."""
    if not tags:
        return ParsedSystemMeta()

    public_list: list[str] = []
    seen_public: set[str] = set()
    valid_until: float | None = None
    supersedes: list[str] = []
    seen_sup: set[str] = set()
    visual_ref = ""
    consolidated_seq: int | None = None

    for raw in tags:
        val = str(raw or "").strip()
        if not val:
            continue
        if not val.startswith(SYS_TAG_NAMESPACE):
            clipped = val[:_MAX_TAG_CHARS].rstrip() if len(val) > _MAX_TAG_CHARS else val
            key = clipped.casefold()
            if key not in seen_public and len(public_list) < _MAX_PUBLIC_TAGS:
                seen_public.add(key)
                public_list.append(clipped)
            continue

        if val.startswith(SYS_VALID_UNTIL_PREFIX):
            raw_ts = val[len(SYS_VALID_UNTIL_PREFIX) :].strip()
            try:
                parsed_ts = float(raw_ts)
            except ValueError:
                parsed_ts = 0.0
            if math.isfinite(parsed_ts) and parsed_ts > 0.0:
                valid_until = parsed_ts
        elif val.startswith(SYS_SUPERSEDES_PREFIX):
            target_id = val[len(SYS_SUPERSEDES_PREFIX) :].strip()
            if (
                target_id
                and len(target_id) <= 128
                and target_id not in seen_sup
                and len(supersedes) < _MAX_SUPERSEDES
            ):
                seen_sup.add(target_id)
                supersedes.append(target_id)
        elif val.startswith(SYS_VISUAL_REF_PREFIX):
            candidate_ref = sanitize_visual_ref(val[len(SYS_VISUAL_REF_PREFIX) :])
            if candidate_ref and not visual_ref:
                visual_ref = candidate_ref
        elif val.startswith(SYS_CONSOLIDATED_SEQ_PREFIX):
            raw_seq = val[len(SYS_CONSOLIDATED_SEQ_PREFIX) :].strip()
            try:
                seq_num = int(raw_seq)
            except ValueError:
                seq_num = -1
            if seq_num >= 0:
                consolidated_seq = (
                    seq_num
                    if consolidated_seq is None
                    else max(consolidated_seq, seq_num)
                )

    return ParsedSystemMeta(
        public_tags=tuple(public_list),
        valid_until=valid_until,
        supersedes_ids=tuple(supersedes),
        visual_ref=visual_ref,
        consolidated_seq=consolidated_seq,
    )


def pack_system_tags(
    public_tags: Sequence[str] = (),
    *,
    valid_until: float | None = None,
    supersedes_ids: Sequence[str] = (),
    visual_ref: str = "",
    consolidated_seq: int | None = None,
) -> tuple[str, ...]:
    """Pack user-visible tags together with encoded `__sys:*` metadata tags."""
    out = list(strip_system_tags(public_tags))

    if valid_until is not None and math.isfinite(float(valid_until)) and float(valid_until) > 0.0:
        out.append(f"{SYS_VALID_UNTIL_PREFIX}{int(round(float(valid_until)))}")

    seen_sup: set[str] = set()
    for raw_id in supersedes_ids:
        tid = str(raw_id or "").strip()
        if tid and len(tid) <= 128 and tid not in seen_sup:
            seen_sup.add(tid)
            out.append(f"{SYS_SUPERSEDES_PREFIX}{tid}")
            if len(seen_sup) >= _MAX_SUPERSEDES:
                break

    clean_ref = sanitize_visual_ref(visual_ref)
    if clean_ref:
        out.append(f"{SYS_VISUAL_REF_PREFIX}{clean_ref}")

    if consolidated_seq is not None and int(consolidated_seq) >= 0:
        out.append(f"{SYS_CONSOLIDATED_SEQ_PREFIX}{int(consolidated_seq)}")

    return tuple(out)


__all__ = [
    "ParsedSystemMeta",
    "SYS_CONSOLIDATED_SEQ_PREFIX",
    "SYS_SUPERSEDES_PREFIX",
    "SYS_TAG_NAMESPACE",
    "SYS_VALID_UNTIL_PREFIX",
    "SYS_VISUAL_REF_PREFIX",
    "is_system_tag",
    "pack_system_tags",
    "sanitize_visual_ref",
    "strip_system_tags",
    "unpack_system_tags",
]

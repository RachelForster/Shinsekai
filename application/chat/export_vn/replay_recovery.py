"""Chronological dialogId and replay-frame recovery for legacy or unindexed histories."""

from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path
import re
from typing import Any

from application.chat.history.replay import split_text
from application.chat.history.replay_store import ReplayStore
from application.chat.host.history import _serialize_history_entries_from_messages
from config.config_manager import character_name_key

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _speaker_key(name: str) -> str:
    clean = str(name or "").strip()
    return character_name_key(clean) if clean else ""


def _backfill_from_raw_messages(
    parsed_raw: list[tuple[dict[str, Any], str, str, bool, bool]],
    missing_indices: list[int],
    *,
    raw_messages: list[Any],
    user_name: str,
) -> dict[int, str]:
    known_ids = {
        str(parsed_raw[idx][0].get("dialogId") or "").strip()
        for idx, (_raw, _sp, _body, sys_hidden, options_row) in enumerate(parsed_raw)
        if not sys_hidden and not options_row and str(parsed_raw[idx][0].get("dialogId") or "").strip()
    }
    derived = _serialize_history_entries_from_messages(raw_messages, user_name)
    queues: dict[tuple[str, str], deque[str]] = defaultdict(deque)
    for item in derived:
        if str(item.get("role") or "") != "assistant":
            continue
        did = str(item.get("dialogId") or "").strip()
        if not _HEX64_RE.fullmatch(did) or did in known_ids:
            continue
        sp, body = split_text(item)
        queues[(_speaker_key(sp), body.strip())].append(did)

    recovered: dict[int, str] = {}
    for idx in missing_indices:
        raw, speaker, body, _sys_hidden, _options_row = parsed_raw[idx]
        if str(raw.get("dialogId") or "").strip():
            continue
        q = queues.get((_speaker_key(speaker), body.strip()))
        if q:
            recovered[idx] = q.popleft()
    return recovered


def _scan_sorted_replay_frames(store_dir: Path) -> list[tuple[str, tuple[str, str]]]:
    candidates: list[tuple[int, str, Path]] = []
    for fp in store_dir.glob("*.frame.json"):
        did = fp.name[: -len(".frame.json")]
        if not _HEX64_RE.fullmatch(did):
            continue
        try:
            mtime_ns = fp.stat().st_mtime_ns
        except OSError:
            continue
        candidates.append((mtime_ns, fp.name, fp))
    candidates.sort(key=lambda item: (item[0], item[1]))

    frames: list[tuple[str, tuple[str, str]]] = []
    for _mtime, name, fp in candidates:
        did = name[: -len(".frame.json")]
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        msg = payload.get("message")
        if not isinstance(msg, dict):
            continue
        sp = str(msg.get("name") or "").strip()
        txt = str(msg.get("text") or "").strip()
        if not sp and not txt:
            continue
        frames.append((did, (_speaker_key(sp), txt)))
    return frames


def _align_frames_monotonically(
    parsed_raw: list[tuple[dict[str, Any], str, str, bool, bool]],
    recovered: dict[int, str],
    frames: list[tuple[str, tuple[str, str]]],
) -> dict[int, str]:
    n = len(frames)
    if not n:
        return {}
    frame_index_by_id = {did: j for j, (did, _key) in enumerate(frames)}
    positions_by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for j, (_did, key) in enumerate(frames):
        positions_by_key[key].append(j)

    assistant_rows: list[int] = [
        idx
        for idx, (raw, _sp, _body, sys_hidden, options_row) in enumerate(parsed_raw)
        if not sys_hidden and not options_row and str(raw.get("role") or "assistant") == "assistant"
    ]
    if not assistant_rows:
        return {}

    tree: list[tuple[int, int, int]] = [(0, 0, -1)] * (n + 1)
    nodes: list[tuple[int, str, int]] = []

    def query(limit: int) -> tuple[int, int, int]:
        best = (0, 0, -1)
        k = limit
        while k > 0:
            cur = tree[k]
            if cur[0] > best[0] or (cur[0] == best[0] and cur[1] > best[1]):
                best = cur
            k -= k & -k
        return best

    def update(pos: int, val: tuple[int, int, int]) -> None:
        k = pos
        while k <= n:
            cur = tree[k]
            if val[0] > cur[0] or (val[0] == cur[0] and val[1] > cur[1]):
                tree[k] = val
            k += k & -k

    for row_idx in reversed(assistant_rows):
        raw, speaker, body, _sys, _opt = parsed_raw[row_idx]
        known_did = recovered.get(row_idx) or str(raw.get("dialogId") or "").strip()
        if known_did in frame_index_by_id:
            cands = (frame_index_by_id[known_did],)
        else:
            cands = tuple(positions_by_key.get((_speaker_key(speaker), body.strip()), ()))
        for j in cands:
            r = n - j
            best_cnt, best_sum, next_node = query(r - 1)
            nodes.append((row_idx, frames[j][0], next_node))
            update(r, (best_cnt + 1, best_sum + j, len(nodes) - 1))

    matched: dict[int, str] = {}
    _cnt, _sum, head = query(n)
    while head >= 0:
        row_idx, frame_did, next_node = nodes[head]
        matched[row_idx] = frame_did
        head = next_node
    return matched


def recover_missing_dialog_ids(
    parsed_raw: list[tuple[dict[str, Any], str, str, bool, bool]],
    *,
    raw_messages: list[Any],
    user_name: str,
    store: ReplayStore,
) -> dict[int, str]:
    """Recover missing dialog IDs from user-turn IDs or chronological replay frames."""
    missing_indices: list[int] = []
    for idx, (raw, _sp, _body, sys_hidden, options_row) in enumerate(parsed_raw):
        if sys_hidden or options_row or str(raw.get("role") or "assistant") != "assistant":
            continue
        did = str(raw.get("dialogId") or "").strip()
        if not did or store.read(did, "frame.json") is None:
            missing_indices.append(idx)
    if not missing_indices:
        return {}

    recovered = _backfill_from_raw_messages(
        parsed_raw,
        missing_indices,
        raw_messages=raw_messages,
        user_name=user_name,
    )
    still_missing = {
        idx
        for idx in missing_indices
        if not (
            (recovered.get(idx) or str(parsed_raw[idx][0].get("dialogId") or "").strip())
            and store.read(
                recovered.get(idx) or str(parsed_raw[idx][0].get("dialogId") or "").strip(),
                "frame.json",
            )
            is not None
        )
    }
    if not still_missing or not store.directory.is_dir():
        return recovered

    frames = _scan_sorted_replay_frames(store.directory)
    aligned = _align_frames_monotonically(parsed_raw, recovered, frames)
    for idx in still_missing:
        frame_did = aligned.get(idx)
        if frame_did:
            recovered[idx] = frame_did
    return recovered


__all__ = ["recover_missing_dialog_ids"]

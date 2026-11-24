"""Session, anchor, and range selection validation for playable VN export."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sdk.exception.types import AppError


def validate_expected_session(state: Any, conversation_id: str, expected_session_id: str) -> None:
    """Reject stale active-session exports when the active runtime session has switched."""
    if conversation_id.strip():
        return
    expected = expected_session_id.strip()
    if not expected:
        return
    actual = str((getattr(state, "chat_session", {}) or {}).get("sessionId") or "").strip()
    if actual != expected:
        raise AppError("vn_export_session_changed", http_status=409)


def _verify_selected_anchors(
    parsed_raw: list[tuple[dict[str, Any], str, str, bool, bool]],
    id_to_raw: dict[str, int],
    anchors: Sequence[dict[str, str]],
) -> None:
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        eid = str(anchor.get("id") or "").strip()
        if not eid or eid not in id_to_raw:
            raise AppError("vn_export_history_changed", http_status=409)
        raw_entry = parsed_raw[id_to_raw[eid]][0]
        if "role" in anchor and str(raw_entry.get("role") or "assistant") != str(anchor.get("role") or ""):
            raise AppError("vn_export_history_changed", http_status=409)
        if "dialogId" in anchor and str(raw_entry.get("dialogId") or "") != str(anchor.get("dialogId") or ""):
            raise AppError("vn_export_history_changed", http_status=409)
        if "text" in anchor and str(raw_entry.get("text") or "") != str(anchor.get("text") or ""):
            raise AppError("vn_export_history_changed", http_status=409)


def resolve_vn_selection(
    parsed_raw: list[tuple[dict[str, Any], str, str, bool, bool]],
    selectable_indices: list[int],
    *,
    selected_entry_ids: Sequence[str],
    selected_entry_anchors: Sequence[dict[str, str]],
    start_entry_id: str,
    end_entry_id: str,
) -> tuple[int, set[int]]:
    """Return ``(max_raw_index, playable_raw_indices_to_emit)`` for exact IDs or inclusive range."""
    req_ids = tuple(dict.fromkeys(str(eid).strip() for eid in selected_entry_ids if str(eid).strip()))
    id_to_raw = {str(parsed_raw[raw_idx][0].get("id") or ""): raw_idx for raw_idx in selectable_indices}

    if req_ids:
        matched_raw: list[int] = []
        for eid in req_ids:
            if eid not in id_to_raw:
                raise AppError("vn_export_history_changed" if selected_entry_anchors else "vn_export_invalid_range", http_status=409 if selected_entry_anchors else 400)
            matched_raw.append(id_to_raw[eid])
        if selected_entry_anchors:
            _verify_selected_anchors(parsed_raw, id_to_raw, selected_entry_anchors)
        emit_set = {raw_idx for raw_idx in matched_raw if not parsed_raw[raw_idx][4]}
        if not emit_set:
            raise AppError("vn_export_no_playable_entries", http_status=400)
        return max(matched_raw), emit_set

    visible_start = 0
    visible_end = len(selectable_indices) - 1
    if start_entry_id.strip():
        target = start_entry_id.strip()
        matches = [i for i, raw_idx in enumerate(selectable_indices) if parsed_raw[raw_idx][0].get("id") == target]
        if not matches:
            raise AppError("vn_export_invalid_range", http_status=400)
        visible_start = matches[0]
    if end_entry_id.strip():
        target = end_entry_id.strip()
        matches = [i for i, raw_idx in enumerate(selectable_indices) if parsed_raw[raw_idx][0].get("id") == target]
        if not matches:
            raise AppError("vn_export_invalid_range", http_status=400)
        visible_end = matches[0]
    if visible_start > visible_end:
        raise AppError("vn_export_invalid_range", http_status=400)

    raw_end_idx = selectable_indices[visible_end]
    emit_set = {
        raw_idx
        for raw_idx in selectable_indices[visible_start : visible_end + 1]
        if not parsed_raw[raw_idx][4]
    }
    if not emit_set:
        raise AppError("vn_export_no_playable_entries", http_status=400)
    return raw_end_idx, emit_set


__all__ = ["resolve_vn_selection", "validate_expected_session"]

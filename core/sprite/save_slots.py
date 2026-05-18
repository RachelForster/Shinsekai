"""Galgame-style save slots for desktop chat sessions."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from llm.history_manager import parse_assistant_dialog_content

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAVE_DIR = PROJECT_ROOT / "data" / "chat_saves"
MANUAL_SLOT_COUNT = 12
AUTO_SLOT_ID = "auto"


@dataclass(frozen=True)
class SaveSlotSummary:
    slot_id: str
    label: str
    path: Path
    exists: bool
    saved_at: str = ""
    preview: str = ""
    message_count: int = 0
    turn_count: int = 0
    background_path: str = ""
    bgm_path: str = ""


def manual_slot_ids(count: int = MANUAL_SLOT_COUNT) -> list[str]:
    return [f"slot_{idx:02d}" for idx in range(1, count + 1)]


def slot_label(slot_id: str) -> str:
    if slot_id == AUTO_SLOT_ID:
        return "Auto"
    match = re.fullmatch(r"slot_(\d{2})", slot_id or "")
    if match:
        return f"Slot {int(match.group(1)):02d}"
    return slot_id


def slot_path(slot_id: str, *, save_dir: Path | None = None) -> Path:
    slot_id = _validate_slot_id(slot_id)
    root = save_dir if save_dir is not None else SAVE_DIR
    return Path(root) / f"{slot_id}.json"


def has_save_slot(slot_id: str, *, save_dir: Path | None = None) -> bool:
    return slot_path(slot_id, save_dir=save_dir).exists()


def list_manual_slots(
    *, save_dir: Path | None = None, count: int = MANUAL_SLOT_COUNT
) -> list[SaveSlotSummary]:
    return [
        summarize_slot(slot_id, save_dir=save_dir)
        for slot_id in manual_slot_ids(count)
    ]


def get_auto_slot_summary(*, save_dir: Path | None = None) -> SaveSlotSummary:
    return summarize_slot(AUTO_SLOT_ID, save_dir=save_dir)


def summarize_slot(
    slot_id: str, *, save_dir: Path | None = None
) -> SaveSlotSummary:
    path = slot_path(slot_id, save_dir=save_dir)
    if not path.exists():
        return SaveSlotSummary(
            slot_id=slot_id,
            label=slot_label(slot_id),
            path=path,
            exists=False,
        )
    try:
        payload = _read_payload(path)
    except Exception:
        return SaveSlotSummary(
            slot_id=slot_id,
            label=slot_label(slot_id),
            path=path,
            exists=True,
            preview="(invalid save)",
        )
    return _summary_from_payload(payload, path)


def save_auto_slot(
    messages: list[dict[str, Any]],
    *,
    background_path: str | None = None,
    bgm_path: str | None = None,
    history_file: str | None = None,
    save_dir: Path | None = None,
) -> SaveSlotSummary:
    return save_slot(
        AUTO_SLOT_ID,
        messages,
        background_path=background_path,
        bgm_path=bgm_path,
        history_file=history_file,
        save_dir=save_dir,
    )


def save_slot(
    slot_id: str,
    messages: list[dict[str, Any]],
    *,
    background_path: str | None = None,
    bgm_path: str | None = None,
    history_file: str | None = None,
    save_dir: Path | None = None,
    saved_at: datetime | None = None,
) -> SaveSlotSummary:
    slot_id = _validate_slot_id(slot_id)
    path = slot_path(slot_id, save_dir=save_dir)
    when = saved_at or datetime.now().astimezone()
    safe_messages = copy.deepcopy(messages or [])
    payload = {
        "version": 1,
        "slot_id": slot_id,
        "slot_label": slot_label(slot_id),
        "saved_at": when.isoformat(timespec="seconds"),
        "history_file": str(history_file or ""),
        "background_path": str(background_path or ""),
        "bgm_path": str(bgm_path or ""),
        "message_count": len(safe_messages),
        "turn_count": count_user_turns(safe_messages),
        "preview": preview_from_messages(safe_messages),
        "messages": safe_messages,
    }
    _write_payload(path, payload)
    return _summary_from_payload(payload, path)


def load_slot(slot_id: str, *, save_dir: Path | None = None) -> dict[str, Any]:
    path = slot_path(slot_id, save_dir=save_dir)
    payload = _read_payload(path)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError(f"Save slot {slot_id!r} has no message list.")
    return payload


def count_user_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for msg in messages or [] if msg.get("role") == "user")


def preview_from_messages(messages: list[dict[str, Any]], max_len: int = 80) -> str:
    for msg in reversed(messages or []):
        role = msg.get("role")
        content = msg.get("content") or ""
        if role == "assistant":
            dialog = parse_assistant_dialog_content(content)
            for item in reversed(dialog):
                speech = str(item.get("speech") or "").strip()
                name = str(item.get("character_name") or "").strip()
                if speech:
                    text = f"{name}: {speech}" if name else speech
                    return _clip_preview(text, max_len)
        elif role == "user":
            text = _strip_local_time(str(content)).strip()
            if text:
                return _clip_preview(text, max_len)
    return ""


def last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return _strip_local_time(str(msg.get("content") or "")).strip()
    return ""


def _validate_slot_id(slot_id: str) -> str:
    slot_id = (slot_id or "").strip()
    if slot_id == AUTO_SLOT_ID or re.fullmatch(r"slot_\d{2}", slot_id):
        return slot_id
    raise ValueError(f"Invalid save slot id: {slot_id!r}")


def _summary_from_payload(payload: dict[str, Any], path: Path) -> SaveSlotSummary:
    slot_id = str(payload.get("slot_id") or path.stem)
    return SaveSlotSummary(
        slot_id=slot_id,
        label=str(payload.get("slot_label") or slot_label(slot_id)),
        path=path,
        exists=True,
        saved_at=str(payload.get("saved_at") or ""),
        preview=str(payload.get("preview") or ""),
        message_count=int(payload.get("message_count") or 0),
        turn_count=int(payload.get("turn_count") or 0),
        background_path=str(payload.get("background_path") or ""),
        bgm_path=str(payload.get("bgm_path") or ""),
    )


def _read_payload(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return {
            "version": 0,
            "slot_id": path.stem,
            "slot_label": slot_label(path.stem),
            "messages": raw,
            "message_count": len(raw),
            "turn_count": count_user_turns(raw),
            "preview": preview_from_messages(raw),
        }
    if not isinstance(raw, dict):
        raise ValueError(f"Save slot file is not an object: {path}")
    raw.setdefault("slot_id", path.stem)
    raw.setdefault("slot_label", slot_label(path.stem))
    return raw


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def _strip_local_time(text: str) -> str:
    return re.sub(r"^\[本地时间 [^\]]+\]\s*", "", text or "", count=1)


def _clip_preview(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

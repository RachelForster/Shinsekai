"""Visual, sprite, background, BGM, CG, and presentation restore event handlers."""

from __future__ import annotations

from core.messaging.stage_effects import (
    character_motion_duration_ms,
    normalize_character_motion,
    normalize_scene_transition,
    scene_transition_duration_ms,
)

from .snapshot import (
    PRESENTATION_KEYS,
    EventDict,
    EventFoldSpec,
    SnapshotDict,
    parse_int,
)


def _fold_presentation_restore(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    presentation = event.get("presentation", {})
    next_snapshot.update(
        {k: v for k, v in presentation.items() if k in PRESENTATION_KEYS}
    )
    next_snapshot["replaySelectedIndex"] = None


def _fold_player_portrait_show(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    next_snapshot["playerPortrait"] = {
        "characterName": str(event.get("characterName") or ""),
        "url": str(event.get("url") or ""),
        "crop": dict(event.get("crop") or {}),
    }


def _fold_sprite_show(next_snapshot: SnapshotDict, event: EventDict) -> None:
    character_name = str(event.get("characterName") or "")
    slot = event.get("slot")
    sprite_id = f"{character_name}:{slot}" if slot is not None else character_name
    current = [
        dict(item)
        for item in (next_snapshot.get("sprites") or [])
        if isinstance(item, dict)
    ]
    current = [
        item
        for item in current
        if item.get("id") != sprite_id
        and item.get("label") != character_name
        and item.get("characterName") != character_name
        and (slot is None or item.get("slot") != slot)
    ]
    next_sprite = {
        "id": sprite_id,
        "label": character_name,
        "path": str(event.get("url") or ""),
        "characterName": character_name,
        "scale": event.get("scale"),
        "slot": slot,
        "avatarType": str(event.get("avatarType") or "static"),
        "modelUrl": str(event.get("modelUrl") or ""),
    }
    for axis in ("x", "y"):
        if event.get(axis) is not None:
            next_sprite[axis] = event.get(axis)
    if event.get("identityKey"):
        next_sprite["identityKey"] = str(event["identityKey"])
    if event.get("mouthSync"):
        next_sprite["mouthSync"] = str(event["mouthSync"])
    if isinstance(event.get("portraitCrop"), dict):
        next_sprite["portraitCrop"] = dict(event["portraitCrop"])
    current.append(next_sprite)
    next_snapshot["sprites"] = current


def _fold_sprite_remove(next_snapshot: SnapshotDict, event: EventDict) -> None:
    character_name = str(event.get("characterName") or "")
    removed_keys = {character_name} if character_name else set()
    kept_sprites = []
    for item in next_snapshot.get("sprites") or []:
        if not isinstance(item, dict):
            continue
        if (
            item.get("id") == character_name
            or item.get("label") == character_name
            or item.get("characterName") == character_name
        ):
            for key in ("id", "label", "characterName"):
                val = str(item.get(key) or "").strip()
                if val:
                    removed_keys.add(val)
        else:
            kept_sprites.append(item)
    next_snapshot["sprites"] = kept_sprites
    motions = dict(next_snapshot.get("spriteMotions") or {})
    for key in removed_keys:
        motions.pop(key, None)
    next_snapshot["spriteMotions"] = motions


def _fold_sprite_motion(next_snapshot: SnapshotDict, event: EventDict) -> None:
    character_name = str(event.get("characterName") or "").strip()
    motion = normalize_character_motion(event.get("motion"))
    if not (character_name and motion):
        return
    try:
        raw_duration = event.get("durationMs")
        parsed_duration = int(raw_duration) if raw_duration is not None else 0
        duration_ms = (
            parsed_duration
            if parsed_duration > 0
            else character_motion_duration_ms(motion)
        )
    except (TypeError, ValueError):
        duration_ms = character_motion_duration_ms(motion)
    triggered_at = parse_int(event.get("ts"))
    motions = dict(next_snapshot.get("spriteMotions") or {})
    motions[character_name] = {
        "durationMs": duration_ms,
        "expiresAt": triggered_at + duration_ms,
        "motion": motion,
        "seq": int(event.get("seq") or 0),
    }
    next_snapshot["spriteMotions"] = motions


def _fold_sprite_reaction(next_snapshot: SnapshotDict, event: EventDict) -> None:
    try:
        duration_ms = max(800, int(event.get("durationMs") or 3600))
        triggered_at = int(event.get("ts") or 0)
    except (TypeError, ValueError):
        duration_ms = 3600
        triggered_at = 0
    text = str(event.get("text") or "").strip()
    if text:
        next_snapshot["spriteReaction"] = {
            "characterName": str(event.get("characterName") or ""),
            "text": text,
            "durationMs": duration_ms,
            "expiresAt": triggered_at + duration_ms,
            "seq": int(event.get("seq") or 0),
        }
    else:
        next_snapshot["spriteReaction"] = None


def _fold_background_change(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    background_path = str(event.get("url") or "")
    if background_path != (next_snapshot.get("backgroundPath") or ""):
        next_snapshot["sprites"] = []
        next_snapshot["spriteMotions"] = {}
    next_snapshot["backgroundPath"] = background_path
    transition = normalize_scene_transition(event.get("transition"))
    try:
        raw_duration = event.get("transitionDurationMs")
        duration_ms = (
            int(raw_duration)
            if raw_duration is not None
            else scene_transition_duration_ms(transition)
        )
    except (TypeError, ValueError):
        duration_ms = scene_transition_duration_ms(transition)
    triggered_at = parse_int(event.get("ts"))
    if transition and duration_ms > 0:
        next_snapshot["backgroundTransition"] = {
            "durationMs": duration_ms,
            "effect": transition,
            "expiresAt": triggered_at + duration_ms,
            "seq": int(event.get("seq") or 0),
        }
    else:
        next_snapshot["backgroundTransition"] = None


def _fold_bgm_change(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["bgmPath"] = str(event.get("url") or "")


def _fold_cg_show(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["cgPath"] = str(event.get("url") or "")


def _fold_cg_hide(next_snapshot: SnapshotDict, _event: EventDict) -> None:
    next_snapshot["cgPath"] = ""


HANDLERS: dict[str, EventFoldSpec] = {
    "background.change": EventFoldSpec(
        _fold_background_change, clear_transient_notice=True
    ),
    "bgm.change": EventFoldSpec(_fold_bgm_change),
    "cg.show": EventFoldSpec(_fold_cg_show, clear_transient_notice=True),
    "cg.hide": EventFoldSpec(_fold_cg_hide),
    "sprite.show": EventFoldSpec(_fold_sprite_show, clear_transient_notice=True),
    "sprite.remove": EventFoldSpec(_fold_sprite_remove),
    "sprite.motion": EventFoldSpec(_fold_sprite_motion),
    "sprite.reaction": EventFoldSpec(_fold_sprite_reaction),
    "player.portrait.show": EventFoldSpec(_fold_player_portrait_show),
    "presentation.restore": EventFoldSpec(_fold_presentation_restore),
}

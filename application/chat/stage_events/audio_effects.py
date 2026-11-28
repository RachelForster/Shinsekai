"""Audio playback, loop effect, image effect, and ambient effect event handlers."""

from __future__ import annotations

import math

from .snapshot import EventDict, EventFoldSpec, SnapshotDict


def _without_key(items: object, key: str) -> list[dict]:
    return [
        dict(item)
        for item in (items or [])
        if isinstance(item, dict) and str(item.get("key") or "") != key
    ]


def _fold_tts_play(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["status"] = "speaking"
    next_snapshot["characterName"] = str(event.get("characterName") or "")
    raw_volume = event.get("volume")
    next_snapshot["activePlayback"] = {
        "characterName": str(event.get("characterName") or ""),
        "playbackId": str(event.get("playbackId") or ""),
        "rendererId": str(event.get("rendererId") or ""),
        "seq": int(event.get("seq") or 0),
        "url": str(event.get("url") or ""),
        "volume": (
            max(0.0, min(1.0, float(raw_volume)))
            if isinstance(raw_volume, (int, float))
            and not isinstance(raw_volume, bool)
            and math.isfinite(float(raw_volume))
            else 1.0
        ),
    }


def _fold_tts_skip(next_snapshot: SnapshotDict, event: EventDict) -> None:
    active_playback = next_snapshot.get("activePlayback")
    playback_id = str(event.get("playbackId") or "")
    should_stop = (
        not playback_id
        or not isinstance(active_playback, dict)
        or str(active_playback.get("playbackId") or "") == playback_id
    )
    if should_stop:
        next_snapshot["activePlayback"] = None
        if str(next_snapshot.get("status") or "") == "speaking":
            next_snapshot["status"] = "idle"


def _fold_effect_play(_next_snapshot: SnapshotDict, _event: EventDict) -> None:
    return None


def _fold_effect_image_show(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    try:
        duration_ms = max(0, int(event.get("durationMs") or 0))
        triggered_at = int(event.get("ts") or 0)
    except (TypeError, ValueError):
        duration_ms = 0
        triggered_at = 0
    next_snapshot["effectImage"] = {
        "expiresAt": triggered_at + duration_ms,
        "durationMs": duration_ms,
        "label": str(event.get("label") or ""),
        "seq": int(event.get("seq") or 0),
        "url": str(event.get("url") or ""),
    }


def _fold_effect_loop_start(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    key = str(event.get("key") or "")
    current = _without_key(next_snapshot.get("loopingEffects"), key)
    if key:
        current.append(
            {
                "key": key,
                "seq": int(event.get("seq") or 0),
                "url": str(event.get("url") or ""),
            }
        )
    next_snapshot["loopingEffects"] = current[-32:]


def _fold_effect_loop_stop(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    key = str(event.get("key") or "")
    next_snapshot["loopingEffects"] = _without_key(
        next_snapshot.get("loopingEffects"), key
    )


def _fold_effect_loop_stop_all(
    next_snapshot: SnapshotDict, _event: EventDict
) -> None:
    next_snapshot["loopingEffects"] = []


def _fold_ambient_start(next_snapshot: SnapshotDict, event: EventDict) -> None:
    key = str(event.get("key") or "")
    current = _without_key(next_snapshot.get("ambientEffects"), key)
    if key:
        current.append(
            {
                "audioUrl": str(event.get("audioUrl") or ""),
                "key": key,
                "layer": "front" if event.get("layer") == "front" else "back",
                "seq": int(event.get("seq") or 0),
                "url": str(event.get("url") or ""),
            }
        )
    next_snapshot["ambientEffects"] = current[-32:]


def _fold_ambient_layer(next_snapshot: SnapshotDict, event: EventDict) -> None:
    key = str(event.get("key") or "")
    layer = "front" if event.get("layer") == "front" else "back"
    has_audio_url = "audioUrl" in event and event.get("audioUrl") is not None
    audio_url = str(event.get("audioUrl") or "") if has_audio_url else ""
    next_snapshot["ambientEffects"] = [
        {
            **dict(item),
            "layer": layer,
            **({"audioUrl": audio_url} if has_audio_url else {}),
        }
        if str(item.get("key") or "") == key
        else dict(item)
        for item in (next_snapshot.get("ambientEffects") or [])
        if isinstance(item, dict)
    ]


def _fold_ambient_stop(next_snapshot: SnapshotDict, event: EventDict) -> None:
    key = str(event.get("key") or "")
    next_snapshot["ambientEffects"] = _without_key(
        next_snapshot.get("ambientEffects"), key
    )


def _fold_ambient_stop_all(
    next_snapshot: SnapshotDict, _event: EventDict
) -> None:
    next_snapshot["ambientEffects"] = []


HANDLERS: dict[str, EventFoldSpec] = {
    "tts.play": EventFoldSpec(_fold_tts_play, clear_transient_notice=True),
    "tts.skip": EventFoldSpec(_fold_tts_skip),
    "effect.play": EventFoldSpec(_fold_effect_play),
    "effect.image.show": EventFoldSpec(_fold_effect_image_show),
    "effect.loop.start": EventFoldSpec(_fold_effect_loop_start),
    "effect.loop.stop": EventFoldSpec(_fold_effect_loop_stop),
    "effect.loop.stop-all": EventFoldSpec(_fold_effect_loop_stop_all),
    "ambient.start": EventFoldSpec(_fold_ambient_start),
    "ambient.layer": EventFoldSpec(_fold_ambient_layer),
    "ambient.stop": EventFoldSpec(_fold_ambient_stop),
    "ambient.stop-all": EventFoldSpec(_fold_ambient_stop_all),
}

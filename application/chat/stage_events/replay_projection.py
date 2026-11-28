"""Replay checkpoint projection derived from the unified stage snapshot."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

REPLAY_OBSERVED_EVENTS = frozenset(
    {
        "background.change",
        "bgm.change",
        "cg.show",
        "cg.hide",
        "ambient.start",
        "ambient.layer",
        "ambient.stop",
        "ambient.stop-all",
        "sprite.show",
        "sprite.remove",
        "stats.update",
        "player.portrait.show",
    }
)


def project_replay_frame(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Extract portable replay presentation checkpoint fields from a stage snapshot."""
    sprites: list[dict[str, Any]] = []
    for sprite in snapshot.get("sprites") or ():
        if not isinstance(sprite, dict):
            continue
        item = {k: v for k, v in sprite.items() if k != "transitions"}
        item["applyMode"] = "restore"
        item["id"] = str(
            sprite.get("characterName")
            or sprite.get("label")
            or sprite.get("slot", 0)
        )
        sprites.append(item)

    frame: dict[str, Any] = {
        "backgroundPath": snapshot.get("backgroundPath") or "",
        "bgmPath": snapshot.get("bgmPath") or "",
        "cgPath": snapshot.get("cgPath") or "",
        "ambientEffects": copy.deepcopy(snapshot.get("ambientEffects") or []),
        "sprites": sprites,
        "stats": copy.deepcopy(snapshot.get("stats") or []),
    }
    if snapshot.get("playerPortrait"):
        frame["playerPortrait"] = copy.deepcopy(snapshot["playerPortrait"])
    return frame

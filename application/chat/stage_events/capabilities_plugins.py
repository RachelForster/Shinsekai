"""Story, behavior, outfit, memory mode, and plugin presentation event handlers."""

from __future__ import annotations

from .snapshot import EventDict, EventFoldSpec, EventHandler, SnapshotDict

_STORY_LAST_EVENT_TYPES = (
    "story.node.entered",
    "story.node.unlocked",
    "story.cast.replace",
    "story.ending.reached",
)


def _fold_story_state_replace(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    story = event.get("story")
    if isinstance(story, dict):
        next_snapshot["story"] = dict(story)


def _fold_behavior_state_replace(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    behavior = event.get("behavior")
    next_snapshot["behavior"] = (
        dict(behavior) if isinstance(behavior, dict) else None
    )


def _make_story_last_event_handler(event_type: str) -> EventHandler:
    def _handle(next_snapshot: SnapshotDict, event: EventDict) -> None:
        existing = next_snapshot.get("story")
        if not isinstance(existing, dict):
            return
        story = dict(existing)
        payload = event.get("payload")
        if isinstance(payload, dict):
            story["lastEvent"] = {
                "type": event_type,
                "payload": dict(payload),
                "revision": event.get("revision"),
            }
        next_snapshot["story"] = story

    return _handle


def _fold_outfit_state(next_snapshot: SnapshotDict, event: EventDict) -> None:
    outfits = event.get("outfits")
    if isinstance(outfits, dict):
        next_snapshot["outfits"] = {
            str(cname): dict(state_item)
            for cname, state_item in outfits.items()
            if str(cname).strip() and isinstance(state_item, dict)
        }
    if isinstance(event.get("autoOutfitSwitch"), bool):
        next_snapshot["autoOutfitSwitch"] = bool(event["autoOutfitSwitch"])
    catalog = event.get("outfitCatalog")
    if isinstance(catalog, dict):
        next_snapshot["outfitCatalog"] = {
            str(cname): dict(entry)
            for cname, entry in catalog.items()
            if str(cname).strip() and isinstance(entry, dict)
        }


def _fold_memory_mode(next_snapshot: SnapshotDict, event: EventDict) -> None:
    mode = str(event.get("memoryMode") or "").strip()
    if mode in {"isolated", "shared", "inherit_readonly"}:
        next_snapshot["memoryMode"] = mode


def _fold_plugin_page_present(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    plugin_id = str(event.get("pluginId") or "").strip()[:128]
    page_id = str(event.get("pageId") or "").strip()[:128]
    presentation_id = str(event.get("presentationId") or "").strip()[:128]
    if not plugin_id or not page_id or not presentation_id:
        return
    current = [
        dict(item)
        for item in (next_snapshot.get("pluginPagePresentations") or [])
        if isinstance(item, dict)
        and (
            str(item.get("pluginId") or "") != plugin_id
            or str(item.get("presentationId") or "") != presentation_id
        )
    ]
    current.append(
        {
            "mode": "overlay",
            "pageId": page_id,
            "payload": (
                dict(event.get("payload"))
                if isinstance(event.get("payload"), dict)
                else {}
            ),
            "pluginId": plugin_id,
            "presentationId": presentation_id,
        }
    )
    next_snapshot["pluginPagePresentations"] = current[-8:]


def _fold_plugin_page_dismiss(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    plugin_id = str(event.get("pluginId") or "").strip()
    presentation_id = str(event.get("presentationId") or "").strip()
    next_snapshot["pluginPagePresentations"] = [
        dict(item)
        for item in (next_snapshot.get("pluginPagePresentations") or [])
        if isinstance(item, dict)
        and (
            str(item.get("pluginId") or "") != plugin_id
            or str(item.get("presentationId") or "") != presentation_id
        )
    ]


HANDLERS: dict[str, EventFoldSpec] = {
    "story.state.replace": EventFoldSpec(_fold_story_state_replace),
    **{
        event_type: EventFoldSpec(_make_story_last_event_handler(event_type))
        for event_type in _STORY_LAST_EVENT_TYPES
    },
    "behavior.state.replace": EventFoldSpec(_fold_behavior_state_replace),
    "outfit.state": EventFoldSpec(_fold_outfit_state),
    "memory.mode": EventFoldSpec(_fold_memory_mode),
    "plugin.page.present": EventFoldSpec(_fold_plugin_page_present),
    "plugin.page.dismiss": EventFoldSpec(_fold_plugin_page_dismiss),
}

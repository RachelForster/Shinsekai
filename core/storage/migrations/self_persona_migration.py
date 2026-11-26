"""Schema v2 migration promoting legacy self-persona ``display_name`` to ``name``."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any
import uuid

from config.models import SELF_PERSONA_ID, is_self_persona_name

logger = logging.getLogger(__name__)


def _replace_name(value: Any, old_cf: str, new_name: str) -> Any:
    if isinstance(value, str) and value.strip().casefold() == old_cf:
        return new_name
    return value


def _rename_relation_graph_dict(graph: Any, old_name: str, new_name: str) -> tuple[Any, bool]:
    if not isinstance(graph, dict):
        return graph, False
    old_cf = old_name.strip().casefold()
    new_cf = new_name.strip().casefold()
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return graph, False
    existing_keys = {
        str(node.get("key") or "").strip().casefold()
        for node in nodes
        if isinstance(node, dict)
    }
    if old_cf not in existing_keys or new_cf in existing_keys:
        return graph, False

    changed = False
    next_nodes = []
    for node in nodes:
        if isinstance(node, dict) and str(node.get("key") or "").strip().casefold() == old_cf:
            next_nodes.append({**node, "key": new_name})
            changed = True
        else:
            next_nodes.append(node)

    edges = graph.get("edges")
    next_edges = edges
    if isinstance(edges, list):
        next_edges = []
        for edge in edges:
            if not isinstance(edge, dict):
                next_edges.append(edge)
                continue
            src = edge.get("source")
            tgt = edge.get("target")
            next_src = _replace_name(src, old_cf, new_name)
            next_tgt = _replace_name(tgt, old_cf, new_name)
            if next_src != src or next_tgt != tgt:
                next_edges.append({**edge, "source": next_src, "target": next_tgt})
                changed = True
            else:
                next_edges.append(edge)

    if not changed:
        return graph, False
    return {**graph, "nodes": next_nodes, "edges": next_edges}, True


def _rename_launch_payload(launch: Any, old_cf: str, new_name: str) -> tuple[Any, bool]:
    if not isinstance(launch, dict):
        return launch, False
    updated = dict(launch)
    changed = False
    for key in ("playerCharacter", "player_character"):
        if key in updated:
            nxt = _replace_name(updated[key], old_cf, new_name)
            if nxt != updated[key]:
                updated[key] = nxt
                changed = True
    for list_key in (
        "characters",
        "primaryCharacters",
        "primary_characters",
        "selectedCharacters",
        "selected_characters",
    ):
        raw_list = updated.get(list_key)
        if isinstance(raw_list, list):
            next_list = [_replace_name(item, old_cf, new_name) for item in raw_list]
            if next_list != raw_list:
                updated[list_key] = next_list
                changed = True
    editor_session = updated.get("editorSession")
    if isinstance(editor_session, dict):
        next_session, sess_changed = _rename_launch_payload(editor_session, old_cf, new_name)
        if sess_changed:
            updated["editorSession"] = next_session
            changed = True
    manual = bool(updated.get("systemManuallyEdited")) or (
        isinstance(updated.get("editorSession"), dict)
        and bool(updated["editorSession"].get("systemManuallyEdited"))
    )
    has_system = bool(str(updated.get("system") or "").strip()) or (
        isinstance(updated.get("editorSession"), dict)
        and bool(str(updated["editorSession"].get("system") or "").strip())
    )
    if changed and not updated.get("storyPath") and not manual and has_system:
        updated["systemStale"] = True
    return (updated if changed else launch), changed


def rename_template_session_dict(
    raw: dict[str, Any],
    old_name: str,
    new_name: str,
) -> tuple[dict[str, Any], bool]:
    """Cascade a character rename into a raw template session dictionary."""
    old_cf = str(old_name or "").strip().casefold()
    new_cf = str(new_name or "").strip().casefold()
    if not old_cf or not new_cf or old_cf == new_cf:
        return raw, False
    updated = dict(raw)
    changed = False
    if "player_character" in updated:
        nxt_player = _replace_name(updated.get("player_character"), old_cf, new_name)
        if nxt_player != updated.get("player_character"):
            updated["player_character"] = nxt_player
            changed = True
    for list_key in ("selected_characters", "primary_characters"):
        items = updated.get(list_key)
        if isinstance(items, list):
            nxt_items = [_replace_name(item, old_cf, new_name) for item in items]
            if nxt_items != items:
                updated[list_key] = nxt_items
                changed = True
    if (
        (changed or is_self_persona_name(old_name))
        and not bool(updated.get("system_manually_edited"))
        and str(updated.get("system_template_text") or "").strip()
    ):
        updated["system_stale"] = True
        changed = True
    return (updated if changed else raw), changed


def _bump_meta(connection: sqlite3.Connection, table_names: tuple[str, ...]) -> None:
    for meta_key in table_names:
        connection.execute(
            """
            INSERT INTO _catalog_meta(table_name, revision) VALUES (?, ?)
            ON CONFLICT(table_name) DO UPDATE SET revision = excluded.revision
            """,
            (meta_key, uuid.uuid4().hex),
        )


def migrate_v2_self_persona_display_name(connection: sqlite3.Connection) -> None:
    """Promote legacy ``__self__.display_name`` into ``Character.name`` on schema v2 upgrade."""
    self_row = connection.execute(
        "SELECT id, name, payload_json FROM characters WHERE id = ? LIMIT 1",
        (SELF_PERSONA_ID,),
    ).fetchone()
    if self_row is None:
        return

    current_name = str(self_row["name"] or "").strip()
    if not is_self_persona_name(current_name):
        return

    try:
        self_payload = json.loads(str(self_row["payload_json"]))
    except ValueError:
        return
    if not isinstance(self_payload, dict):
        return

    display_name = str(self_payload.get("display_name") or "").strip()
    if not display_name or display_name.casefold() == current_name.casefold():
        return

    collision = connection.execute(
        "SELECT 1 FROM characters WHERE id != ? AND name = ? COLLATE NOCASE LIMIT 1",
        (SELF_PERSONA_ID, display_name),
    ).fetchone()
    if collision is not None:
        logger.warning(
            "Skipping self-persona display_name promotion for %r due to existing character name conflict",
            display_name,
        )
        return

    now = time.time()
    old_cf = current_name.casefold()
    updated_self_payload = {
        **self_payload,
        "name": display_name,
        "display_name": "",
    }
    graph, graph_changed = _rename_relation_graph_dict(
        updated_self_payload.get("relation_graph"), current_name, display_name
    )
    if graph_changed:
        updated_self_payload["relation_graph"] = graph

    connection.execute(
        "UPDATE characters SET name = ?, payload_json = ?, updated_at = ? WHERE id = ?",
        (
            display_name,
            json.dumps(updated_self_payload, ensure_ascii=False),
            now,
            SELF_PERSONA_ID,
        ),
    )

    other_rows = connection.execute(
        "SELECT id, payload_json FROM characters WHERE id != ?",
        (SELF_PERSONA_ID,),
    ).fetchall()
    for row in other_rows:
        try:
            other_payload = json.loads(str(row["payload_json"]))
        except ValueError:
            continue
        if not isinstance(other_payload, dict):
            continue
        next_graph, changed = _rename_relation_graph_dict(
            other_payload.get("relation_graph"), current_name, display_name
        )
        if changed:
            other_payload = {**other_payload, "relation_graph": next_graph}
            connection.execute(
                "UPDATE characters SET payload_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(other_payload, ensure_ascii=False), now, str(row["id"])),
            )

    conv_changed = False
    conv_rows = connection.execute("SELECT id, payload_json FROM conversations").fetchall()
    for row in conv_rows:
        try:
            conv_payload = json.loads(str(row["payload_json"]))
        except ValueError:
            continue
        if not isinstance(conv_payload, dict) or not isinstance(conv_payload.get("launch"), dict):
            continue
        next_launch, changed = _rename_launch_payload(conv_payload["launch"], old_cf, display_name)
        if changed:
            conv_payload = {**conv_payload, "launch": next_launch}
            connection.execute(
                "UPDATE conversations SET payload_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(conv_payload, ensure_ascii=False), now, str(row["id"])),
            )
            conv_changed = True

    meta_tables = ("characters", "characters:static", "conversations") if conv_changed else (
        "characters",
        "characters:static",
    )
    _bump_meta(connection, meta_tables)


__all__ = ["migrate_v2_self_persona_display_name", "rename_template_session_dict"]

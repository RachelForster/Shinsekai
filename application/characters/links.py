"""Use Doki's single link registry from the existing local bridge."""
import json
from pathlib import Path
import urllib.request

from config.character_identity import installation_id


def link_operation(use_case, payload):
    root = Path(use_case._resource_paths.project_root)
    identity = installation_id(root)
    character_id = str(payload.get("characterId") or "")
    character = next((c for c in use_case._state.config_manager.config.characters if c.id == character_id), None)
    if character is None:
        raise ValueError("请先保存当前角色。")
    action = payload.get("action", "state")
    body = {"shinsekai_instance": identity, "shinsekai_id": character.id}
    if action == "doki-list":
        body = {}
    elif action == "bind":
        body = {"root": str(root), "shinsekai_id": character.id, "doki_id": payload["dokiId"], "role": payload.get("role", "character")}
    elif action == "unlink":
        current = _request("state", body).get("link")
        if not current:
            return {"link": None}
        body = {"link_id": current["id"]}
    elif action != "state":
        raise ValueError("不支持的链接操作。")
    return _request(action, body)


def _request(action, payload):
    request = urllib.request.Request(f"http://127.0.0.1:8000/api/character-links/{action}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read(2 * 1024**2))
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read(8192)).get("detail", "角色链接失败。")
        raise ValueError(detail) from exc

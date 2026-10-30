"""Add persistent identities without changing character content or resource paths."""
import json
import os
from pathlib import Path
from uuid import uuid4


def ensure_character_ids(rows):
    changed = False
    seen = set()
    for row in rows:
        identity = str(row.get("id") or "").strip()
        if not identity or identity in seen:
            identity = str(uuid4())
            row["id"] = identity
            changed = True
        seen.add(identity)
    return changed


def installation_id(root):
    folder = Path(root) / "data/config"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "integration-instance.json"
    if not path.exists():
        try:
            with path.open("x", encoding="utf-8") as output:
                json.dump({"id": str(uuid4())}, output)
        except FileExistsError:
            pass
    return json.loads(path.read_text(encoding="utf-8"))["id"]

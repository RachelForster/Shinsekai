"""Validate directed transitions without relying on mutable sprite indices."""

from functools import lru_cache
import hashlib
from pathlib import Path

from core.sprite.selection import resolve_runtime_path, sprite_entry_path

TRANSITION_FRAME_COUNT = 22


def field(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


@lru_cache(maxsize=512)
def _digest(path, mtime, size):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sprite_fingerprint(path):
    resolved = resolve_runtime_path(str(path))
    stat = resolved.stat()
    return _digest(str(resolved), stat.st_mtime_ns, stat.st_size)


def valid_transitions(character):
    paths = {sprite_entry_path(sprite) for sprite in field(character, "sprites", [])}
    for edge in field(character, "sprite_transitions", []) or []:
        start, end = field(edge, "from_path"), field(edge, "to_path")
        if start == end or start not in paths or end not in paths:
            continue
        try:
            clip = resolve_runtime_path(field(edge, "path", ""))
            if (
                clip.suffix.lower() == ".webm"
                and clip.is_file()
                and sprite_fingerprint(start) == field(edge, "from_fingerprint")
                and sprite_fingerprint(end) == field(edge, "to_fingerprint")
            ):
                yield edge
        except (OSError, ValueError):
            continue

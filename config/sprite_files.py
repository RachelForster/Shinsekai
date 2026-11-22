"""Read sprite metadata and identify the exact source asset across host layers."""

from functools import lru_cache
import hashlib

from sdk.path_utils import normalize_path_identity


def sprite_field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


@lru_cache(maxsize=512)
def _digest(path, mtime, size):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sprite_fingerprint(path):
    resolved = normalize_path_identity(str(path), field="initial sprite path")
    stat = resolved.stat()
    return _digest(str(resolved), stat.st_mtime_ns, stat.st_size)

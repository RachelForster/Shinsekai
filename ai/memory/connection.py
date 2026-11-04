"""Local authenticated discovery and process leases; no vector files are shared."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

_leases = {}
_lease_lock = threading.Lock()


def acquire_lease(name, root=None):
    with _lease_lock:
        return _acquire_lease(name, root)


def _acquire_lease(name, root=None):
    path = Path(root or Path.cwd() / "data/memory") / name
    path = path.resolve()
    if str(path) in _leases:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        if stream.tell() == 0:
            stream.write(b"\0"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise RuntimeError("另一进程已持有记忆服务，请连接已有服务，不要重复打开向量库。") from exc
    _leases[str(path)] = stream


def discover(root=None):
    path = Path(root or Path.cwd()) / "data/memory/endpoint.json"
    try:
        if path.stat().st_size > 8192:
            return None
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        url = urlparse(descriptor.get("url", ""))
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"} or not url.port or url.path != "/api/memory" or url.username or url.password or url.query or url.fragment or not descriptor.get("token"):
            return None
        return descriptor
    except (OSError, ValueError, TypeError):
        return None


def publish_endpoint(base_url, token, root=None):
    root = Path(root or Path.cwd())
    try:
        acquire_lease("endpoint.lock", root / "data/memory")
    except RuntimeError:
        return False
    folder = root / "data/memory"
    value = {"version": 1, "url": base_url.rstrip("/") + "/api/memory", "token": token, "pid": os.getpid()}
    target = folder / "endpoint.json"
    temporary = folder / f"endpoint-{uuid4().hex}.json"
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, target)
    return True

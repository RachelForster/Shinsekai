"""Host-scoped and process-scoped registry for managed background servers."""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

from sdk.process_platform import (
    WindowsJobObject,
    extract_process_handle,
    is_pid_alive,
    real_int,
    subprocess_isolation_kwargs,
    terminate_pid,
    terminate_process_tree,
)

HOST_PROCESS_MANIFEST_ENV = "SHINSEKAI_HOST_PROCESS_MANIFEST"
HOST_PID_ENV = "SHINSEKAI_HOST_PID"


@dataclass
class ManagedProcess:
    """Handle representing one registered background subprocess."""

    process: Any | None
    name: str
    kind: str
    scope: str
    pid: int | None
    pgid: int | None
    name_hint: str
    job: WindowsJobObject | None = None
    _registry: ManagedProcessRegistry | None = None

    def stop(self, *, timeout: float = 3.0) -> None:
        if self._registry is not None:
            self._registry._remove_entry(self)
        terminate_process_tree(self.process, timeout=timeout, job=self.job)
        self.job = None

    def forget(self) -> None:
        if self._registry is not None:
            self._registry._remove_entry(self)
        if self.job is not None:
            self.job.close()
            self.job = None


class ManagedProcessRegistry:
    """Central registry for per-process and host-scoped background servers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._local_entries: dict[int, ManagedProcess] = {}
        self._host_owned_entries: dict[int, ManagedProcess] = {}
        self._host_job: WindowsJobObject | None = None
        self._host_manifest_path: Path | None = None
        self._host_pid: int | None = None
        self._atexit_registered = False

    def is_host_managed(self) -> bool:
        return bool(
            self._host_manifest_path is not None
            or str(os.environ.get(HOST_PROCESS_MANIFEST_ENV, "")).strip()
        )

    def _ensure_atexit(self) -> None:
        if not self._atexit_registered:
            atexit.register(self._on_process_exit)
            self._atexit_registered = True

    def _on_process_exit(self) -> None:
        with self._lock:
            is_host = self._host_pid == os.getpid()
        if is_host:
            self.shutdown_host_all(timeout=2.5)
        else:
            self.shutdown_process_scoped(timeout=2.5)

    def activate_host(self, manifest_path: Path | str) -> Path:
        """Enable host-level Job/manifest management inside the Bridge host process."""
        path = Path(manifest_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        for stale in path.parent.glob("managed_processes_*.jsonl"):
            if stale == path:
                continue
            suffix = stale.stem.removeprefix("managed_processes_")
            try:
                old_pid = int(suffix)
            except ValueError:
                old_pid = 0
            if old_pid <= 0 or not is_pid_alive(old_pid):
                try:
                    stale.unlink(missing_ok=True)
                except OSError:
                    pass
        with self._lock:
            self._ensure_atexit()
            if os.name == "nt" and self._host_job is None:
                self._host_job = WindowsJobObject()
            self._host_manifest_path = path
            self._host_pid = os.getpid()
            os.environ[HOST_PROCESS_MANIFEST_ENV] = str(path)
            os.environ[HOST_PID_ENV] = str(os.getpid())
        return path

    def attach_to_host_job(self, proc: Any) -> bool:
        """Attach a descendant process (e.g. chat runtime) to the host Job Object."""
        if proc is None:
            return False
        with self._lock:
            job = self._host_job
        return bool(job is not None and job.assign(proc))

    def _manifest_path(self) -> Path | None:
        with self._lock:
            if self._host_manifest_path is not None:
                return self._host_manifest_path
        raw = str(os.environ.get(HOST_PROCESS_MANIFEST_ENV, "")).strip()
        return Path(raw) if raw else None

    def _append_manifest_event(self, payload: dict[str, Any]) -> None:
        path = self._manifest_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _remove_entry(self, entry: ManagedProcess) -> None:
        key = id(entry.process) if entry.process is not None else -1
        with self._lock:
            self._local_entries.pop(key, None)
            self._host_owned_entries.pop(key, None)
        if entry.scope == "host" and entry.pid is not None:
            self._append_manifest_event({"op": "remove", "pid": entry.pid})

    def register(
        self,
        proc: Any,
        *,
        name: str,
        kind: str,
        scope: str = "process",
        name_hint: str = "",
    ) -> ManagedProcess:
        """Track a newly spawned subprocess under ``process`` or ``host`` lifetime."""
        if proc is None:
            return ManagedProcess(
                process=None, name=name, kind=kind, scope="process",
                pid=None, pgid=None, name_hint=name_hint, _registry=None,
            )
        pid = real_int(getattr(proc, "pid", None))
        pgid = pid
        if os.name != "nt" and pid is not None and hasattr(os, "getpgid"):
            try:
                pgid = int(os.getpgid(pid))
            except OSError:
                pgid = pid
        effective_scope = "host" if (scope == "host" and self.is_host_managed()) else "process"
        job: WindowsJobObject | None = None
        if effective_scope == "process":
            if os.name == "nt" and extract_process_handle(proc) is not None:
                try:
                    job = WindowsJobObject(proc)
                except OSError:
                    job = None
        else:
            self.attach_to_host_job(proc)
        entry = ManagedProcess(
            process=proc,
            name=name,
            kind=kind,
            scope=effective_scope,
            pid=pid,
            pgid=pgid,
            name_hint=name_hint,
            job=job,
            _registry=self,
        )
        with self._lock:
            self._ensure_atexit()
            if effective_scope == "host":
                self._host_owned_entries[id(proc)] = entry
            else:
                self._local_entries[id(proc)] = entry
        if effective_scope == "host" and pid is not None:
            self._append_manifest_event(
                {
                    "op": "add",
                    "pid": pid,
                    "pgid": pgid,
                    "name": name,
                    "kind": kind,
                    "name_hint": name_hint,
                    "ts": time.time(),
                }
            )
        return entry

    def forget(self, proc: Any) -> None:
        """Unregister ``proc`` after an already-verified graceful exit without terminating it."""
        if proc is None:
            return
        key = id(proc)
        with self._lock:
            entry = self._local_entries.pop(key, None) or self._host_owned_entries.pop(key, None)
        if entry is not None:
            entry.forget()

    def stop_process(self, proc: Any, *, timeout: float = 3.0) -> None:
        """Terminate ``proc`` (even across grandchildren) and remove it from tracking."""
        if proc is None:
            return
        key = id(proc)
        with self._lock:
            entry = self._local_entries.pop(key, None) or self._host_owned_entries.pop(key, None)
        if entry is not None:
            entry.stop(timeout=timeout)
            return
        terminate_process_tree(proc, timeout=timeout)

    def shutdown_process_scoped(self, *, timeout: float = 3.0) -> int:
        """Stop all ``scope="process"`` children owned by the current process."""
        with self._lock:
            entries = list(reversed(self._local_entries.values()))
            self._local_entries.clear()
        for entry in entries:
            entry.stop(timeout=timeout)
        return len(entries)

    def _read_active_manifest_records(self) -> list[dict[str, Any]]:
        path = self._manifest_path()
        if path is None or not path.is_file():
            return []
        active: dict[int, dict[str, Any]] = {}
        try:
            for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                op = record.get("op")
                pid = real_int(record.get("pid"))
                if pid is None:
                    continue
                if op == "add":
                    active[pid] = record
                elif op == "remove":
                    active.pop(pid, None)
        except OSError:
            return []
        return list(active.values())

    def shutdown_host_all(self, *, timeout: float = 3.0) -> int:
        """Stop all local + host-scoped processes, reap manifest PIDs, and close host Job."""
        killed = self.shutdown_process_scoped(timeout=timeout)
        with self._lock:
            host_entries = list(reversed(self._host_owned_entries.values()))
            self._host_owned_entries.clear()
        for entry in host_entries:
            entry.stop(timeout=timeout)
            killed += 1

        for record in reversed(self._read_active_manifest_records()):
            pid = real_int(record.get("pid"))
            if pid is None:
                continue
            pgid = real_int(record.get("pgid"))
            hint = str(record.get("name_hint") or "")
            if terminate_pid(pid, pgid=pgid, timeout=timeout, expected_name_hint=hint):
                killed += 1

        manifest = self._manifest_path()
        with self._lock:
            job = self._host_job
            self._host_job = None
            is_owner = self._host_pid == os.getpid()
            self._host_manifest_path = None
            if is_owner:
                self._host_pid = None
                os.environ.pop(HOST_PROCESS_MANIFEST_ENV, None)
                os.environ.pop(HOST_PID_ENV, None)
        if job is not None:
            job.close()
        if manifest is not None and is_owner:
            try:
                manifest.unlink(missing_ok=True)
            except OSError:
                pass
        return killed


_DEFAULT_REGISTRY = ManagedProcessRegistry()


def get_process_registry() -> ManagedProcessRegistry:
    return _DEFAULT_REGISTRY


def is_host_managed() -> bool:
    return _DEFAULT_REGISTRY.is_host_managed()


__all__ = [
    "HOST_PID_ENV",
    "HOST_PROCESS_MANIFEST_ENV",
    "ManagedProcess",
    "ManagedProcessRegistry",
    "WindowsJobObject",
    "get_process_registry",
    "is_host_managed",
    "is_pid_alive",
    "subprocess_isolation_kwargs",
    "terminate_pid",
    "terminate_process_tree",
]

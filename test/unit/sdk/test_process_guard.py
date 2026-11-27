"""Unit and Windows integration tests for sdk.process_guard and sdk.process_platform."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from sdk import process_guard, process_platform
from sdk.process_guard import (
    HOST_PID_ENV,
    HOST_PROCESS_MANIFEST_ENV,
    ManagedProcessRegistry,
    WindowsJobObject,
    is_host_managed,
    is_pid_alive,
    subprocess_isolation_kwargs,
    terminate_pid,
    terminate_process_tree,
)


def _hidden_popen_kwargs() -> dict[str, object]:
    return subprocess_isolation_kwargs(hide_window=True)


def _fake_os(name: str, **attrs: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "name": name,
        "environ": os.environ,
        "getpid": os.getpid,
        "getppid": os.getppid,
    }
    base.update(attrs)
    return SimpleNamespace(**base)


def test_real_int_and_handle_extraction() -> None:
    assert process_platform.real_int(42) == 42
    assert process_platform.real_int(0) is None
    assert process_platform.real_int(-5) is None
    assert process_platform.real_int(True) is None
    assert process_platform.real_int("42") is None

    assert process_platform.extract_process_handle(123) == 123
    assert process_platform.extract_process_handle(SimpleNamespace(_handle=456)) == 456
    assert process_platform.extract_process_handle(SimpleNamespace(_handle=None)) is None
    assert process_platform.extract_process_handle(object()) is None


def test_subprocess_isolation_kwargs_windows_and_posix(monkeypatch) -> None:
    monkeypatch.setattr(process_platform, "os", _fake_os("nt"))
    assert subprocess_isolation_kwargs(hide_window=True) == {
        "creationflags": process_platform._CREATE_NO_WINDOW
    }
    assert subprocess_isolation_kwargs(hide_window=False, new_process_group=True) == {
        "creationflags": process_platform._CREATE_NEW_PROCESS_GROUP
    }
    assert subprocess_isolation_kwargs(hide_window=False, new_process_group=False) == {
        "creationflags": 0
    }

    monkeypatch.setattr(process_platform, "os", _fake_os("posix"))
    assert subprocess_isolation_kwargs(hide_window=True) == {"start_new_session": True}


def test_windows_job_object_noops_safely_on_posix_and_mocks(monkeypatch) -> None:
    job_with_mock = WindowsJobObject(SimpleNamespace(pid=9999))
    assert job_with_mock.assign(SimpleNamespace(pid=9999)) is False
    job_with_mock.close()

    monkeypatch.setattr(process_platform, "os", _fake_os("posix"))
    posix_job = WindowsJobObject()
    assert posix_job._ensure_created() is None
    assert posix_job.assign(1234) is False
    posix_job.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows-only Job Object integration test")
def test_windows_host_job_keeps_grandchild_when_intermediate_exits_and_kills_on_close(
    tmp_path: Path,
) -> None:
    """Intermediate process exit leaves grandchild alive; closing host job kills it."""
    pid_file = tmp_path / "grandchild.pid"
    launcher_code = (
        "import pathlib, subprocess, sys, time\n"
        f"kw = {{'creationflags': {subprocess.CREATE_NO_WINDOW}}}\n"
        "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kw)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(gc.pid), encoding='utf-8')\n"
    )
    host_job = WindowsJobObject()
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", launcher_code],
            **_hidden_popen_kwargs(),
        )
        assert host_job.assign(child) is True
        child.wait(timeout=10)

        deadline = time.monotonic() + 5.0
        while not pid_file.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        grandchild_pid = int(pid_file.read_text(encoding="utf-8").strip())
        assert is_pid_alive(grandchild_pid) is True

        host_job.close()
        dead_by = time.monotonic() + 3.0
        while is_pid_alive(grandchild_pid) and time.monotonic() < dead_by:
            time.sleep(0.05)
        assert is_pid_alive(grandchild_pid) is False
    finally:
        host_job.close()


def test_registry_host_activation_manifest_cleanup_and_scope_behavior(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(HOST_PROCESS_MANIFEST_ENV, raising=False)
    monkeypatch.delenv(HOST_PID_ENV, raising=False)
    monkeypatch.setattr(process_guard, "is_pid_alive", lambda pid: pid == os.getpid())

    stale_manifest = tmp_path / "managed_processes_999999.jsonl"
    stale_manifest.write_text('{"op":"add","pid":123}\n', encoding="utf-8")
    sibling_live = tmp_path / f"managed_processes_{os.getpid()}.jsonl"
    sibling_live.write_text("", encoding="utf-8")

    registry = ManagedProcessRegistry()
    assert registry.is_host_managed() is False

    # Not host-managed yet: scope="host" falls back to "process" so standalone CLI stops it.
    local_fake_events: list[str] = []

    class FakeProc:
        def __init__(self, pid: int = 444444) -> None:
            self.pid = pid
            self._rc: int | None = None

        def poll(self) -> int | None:
            return self._rc

        def terminate(self) -> None:
            local_fake_events.append(f"term:{self.pid}")
            self._rc = 0

        def wait(self, timeout=None) -> int:
            self._rc = 0
            return 0

        def kill(self) -> None:
            local_fake_events.append(f"kill:{self.pid}")
            self._rc = -9

    standalone_proc = FakeProc(555001)
    handle_standalone = registry.register(
        standalone_proc, name="comfyui", kind="t2i", scope="host", name_hint="python"
    )
    assert handle_standalone.scope == "process"
    assert registry.shutdown_process_scoped() == 1
    assert local_fake_events == ["term:555001"]

    # Now activate host lifecycle on a separate manifest path.
    manifest = tmp_path / "managed_processes_active.jsonl"
    registry.activate_host(manifest)
    try:
        assert not stale_manifest.exists()
        assert sibling_live.exists()
        assert registry.is_host_managed() is True
        assert os.environ[HOST_PROCESS_MANIFEST_ENV] == str(manifest.resolve())
        assert os.environ[HOST_PID_ENV] == str(os.getpid())

        # None and inert handles work cleanly.
        inert = registry.register(None, name="noop", kind="t2i")
        assert inert.pid is None
        inert.stop()
        inert.forget()
        registry.forget(None)
        registry.stop_process(None)
        assert registry.attach_to_host_job(None) is False

        host_proc = FakeProc(555002)
        host_handle = registry.register(
            host_proc, name="tts", kind="tts", scope="host", name_hint="python"
        )
        assert host_handle.scope == "host"
        # Process-scoped exit in a child would NOT stop host-scoped processes.
        assert registry.shutdown_process_scoped() == 0
        assert host_proc.poll() is None

        # Stopping by proc removes its add entry from active manifest records.
        registry.stop_process(host_proc)
        assert local_fake_events[-1] == "term:555002"
        assert registry._read_active_manifest_records() == []

        # Second host-scoped entry left active is reaped directly by shutdown_host_all.
        host_proc_2 = FakeProc(555004)
        registry.register(host_proc_2, name="comfyui", kind="t2i", scope="host")
        # Re-activating on existing manifest preserves itself and cleans non-numeric stale files.
        bad_stale = tmp_path / "managed_processes_notanint.jsonl"
        bad_stale.write_text("", encoding="utf-8")
        # Untracked stop_process falls back to terminate_process_tree.
        untracked = FakeProc(555005)
        registry.stop_process(untracked)
        assert local_fake_events[-1] == "term:555005"

        # Simulate another child process having appended an orphaned PID + garbage lines.
        manifest.write_text(
            manifest.read_text(encoding="utf-8")
            + "\n"
            + "not-json\n"
            + json.dumps(["not-a-dict"]) + "\n"
            + json.dumps({"op": "add", "pid": "bad"}) + "\n"
            + json.dumps({"op": "noop", "pid": 555009}) + "\n"
            + json.dumps({"op": "add", "pid": 555003, "pgid": 555003, "name": "c", "kind": "t2i", "name_hint": "python"}) + "\n",
            encoding="utf-8",
        )
        registry.activate_host(manifest)
        assert not bad_stale.exists()

        reaped: list[int] = []
        monkeypatch.setattr(process_guard, "terminate_pid", lambda pid, **_kw: reaped.append(pid) or True)
        count = registry.shutdown_host_all()
        assert count >= 2
        assert reaped == [555003]
        assert not manifest.exists()
        assert HOST_PROCESS_MANIFEST_ENV not in os.environ
    finally:
        registry.shutdown_host_all()


@pytest.mark.skipif(os.name != "nt", reason="Real Windows PID/hint check")
def test_terminate_pid_guards_mismatch_hint_and_kills_matching_real_process() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        **_hidden_popen_kwargs(),
    )
    try:
        assert is_pid_alive(proc.pid) is True
        assert is_pid_alive(-1) is False
        assert terminate_pid(1) is True
        assert terminate_pid(os.getpid()) is False

        # Mismatched expected_name_hint protects against terminating a reused unrelated PID.
        assert terminate_pid(proc.pid, expected_name_hint="totally_unrelated_exe") is False
        assert is_pid_alive(proc.pid) is True

        # Matching hint terminates the process cleanly.
        assert terminate_pid(proc.pid, timeout=3.0, expected_name_hint="python") is True
        proc.wait(timeout=3.0)
        assert is_pid_alive(proc.pid) is False
        assert terminate_pid(proc.pid) is True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_terminate_process_tree_and_pid_posix_and_windows_branches(monkeypatch) -> None:
    # Already-exited process + Job closes job without terminating.
    closed_jobs = []

    class FakeJob:
        def close(self) -> None:
            closed_jobs.append("closed")

    done_proc = SimpleNamespace(poll=lambda: 0)
    terminate_process_tree(None, job=FakeJob())
    terminate_process_tree(done_proc, job=FakeJob())
    assert len(closed_jobs) == 2

    # Hung Windows process triggers job.close(), taskkill, and proc.kill().
    monkeypatch.setattr(process_platform, "os", _fake_os("nt"))
    calls: list[str] = []
    monkeypatch.setattr(process_platform, "_run_taskkill", lambda pid, *, force, timeout=2.5: calls.append(f"taskkill:{pid}:{force}"))

    class HungProc:
        pid = 88811
        _handle = 999

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("cmd", timeout or 1.0)

        def kill(self):
            calls.append("kill")

    terminate_process_tree(HungProc(), timeout=2.0, job=FakeJob())
    assert "terminate" in calls
    assert "taskkill:88811:True" in calls
    assert "kill" in calls
    assert len(closed_jobs) == 3

    # Monkeypatched POSIX branch for terminate_process_tree & terminate_pid.
    pg_signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        process_platform,
        "os",
        _fake_os(
            "posix",
            getpgid=lambda pid: 77700,
            getpgrp=lambda: 11111,
            killpg=lambda pgid, sig: pg_signals.append((pgid, int(sig))),
        ),
    )

    posix_proc = SimpleNamespace(
        pid=77700,
        poll=lambda: None,
        terminate=lambda: calls.append("posix_term"),
        wait=lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)),
        kill=lambda: calls.append("posix_kill"),
    )
    terminate_process_tree(posix_proc, timeout=1.0, job=FakeJob())
    assert pg_signals[0] == (77700, int(signal.SIGTERM))
    assert len(pg_signals) == 2

    # POSIX terminate_pid graceful path + PermissionError is_pid_alive check.
    alive_states = iter([True, True, False])
    monkeypatch.setattr(process_platform, "is_pid_alive", lambda pid: next(alive_states, False))
    monkeypatch.setattr(process_platform, "_process_matches_hint", lambda pid, hint: True)
    pg_signals.clear()
    assert terminate_pid(66600, pgid=66600, timeout=1.0) is True
    assert pg_signals == [(66600, int(signal.SIGTERM))]


def test_is_pid_alive_posix_branches(monkeypatch) -> None:
    monkeypatch.setattr(process_platform, "os", _fake_os("posix", kill=lambda pid, sig: None))
    assert is_pid_alive(12345) is True

    monkeypatch.setattr(
        process_platform,
        "os",
        _fake_os("posix", kill=lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError())),
    )
    assert is_pid_alive(12345) is False

    monkeypatch.setattr(
        process_platform,
        "os",
        _fake_os("posix", kill=lambda pid, sig: (_ for _ in ()).throw(PermissionError())),
    )
    assert is_pid_alive(12345) is True


def test_registry_handles_global_singleton_helpers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(HOST_PROCESS_MANIFEST_ENV, raising=False)
    assert isinstance(process_guard.get_process_registry(), ManagedProcessRegistry)
    assert is_host_managed() is False or bool(os.environ.get(HOST_PROCESS_MANIFEST_ENV))
    manifest = tmp_path / "m.jsonl"
    reg = ManagedProcessRegistry()
    assert reg._read_active_manifest_records() == []
    reg.activate_host(manifest)
    try:
        proc = SimpleNamespace(pid=424242, poll=lambda: 0)
        reg.register(proc, name="n", kind="k", scope="host")
        reg.forget(proc)
        assert reg._read_active_manifest_records() == []
        reg._on_process_exit()
    finally:
        reg.shutdown_host_all()
    reg._on_process_exit()


def test_windows_job_error_and_platform_fallback_paths(monkeypatch) -> None:
    import ctypes

    # Job failure branches via fake kernel32.
    monkeypatch.setattr(process_platform, "os", _fake_os("nt"))
    closed: list[int] = []
    fake_api = SimpleNamespace(
        CreateJobObjectW=lambda *_a: 0,
        SetInformationJobObject=lambda *_a: 0,
        AssignProcessToJobObject=lambda *_a: 0,
        OpenProcess=lambda *_a: 99,
        TerminateProcess=lambda *_a: 1,
        CloseHandle=lambda h: closed.append(h) or 1,
    )

    class _FakeBasic(ctypes.Structure):
        _fields_ = [("LimitFlags", ctypes.c_uint32)]

    class FakeExtended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _FakeBasic)]

    monkeypatch.setattr(process_platform, "_get_kernel32", lambda: (fake_api, FakeExtended))
    with pytest.raises(OSError):
        WindowsJobObject()

    fake_api.CreateJobObjectW = lambda *_a: 77
    with pytest.raises(OSError):
        WindowsJobObject()

    fake_api.SetInformationJobObject = lambda *_a: 1
    with pytest.raises(OSError):
        WindowsJobObject(SimpleNamespace(_handle=123))
    assert 77 in closed

    # Windows terminate_pid TerminateProcess fallback.
    monkeypatch.setattr(process_platform, "_run_taskkill", lambda *_a, **_kw: None)
    monkeypatch.setattr(process_platform, "is_pid_alive", lambda pid: True)
    monkeypatch.setattr(process_platform, "_wait_pid_exit", lambda pid, timeout: False)
    monkeypatch.setattr(process_platform, "_process_matches_hint", lambda pid, hint: True)
    assert terminate_pid(77777, timeout=0.2) is False
    assert 99 in closed

    # POSIX terminate_pid SIGKILL fallback and ps query fallback.
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(
        process_platform,
        "os",
        _fake_os(
            "posix",
            getpgrp=lambda: 1,
            kill=lambda pid, sig: kills.append((pid, int(sig))),
        ),
    )
    assert terminate_pid(77778, pgid=None, timeout=0.2) is False
    assert len(kills) == 2


def test_posix_process_matches_hint_queries_proc_and_ps(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(process_platform, "os", _fake_os("posix"))
    monkeypatch.setattr(
        process_platform.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(stdout="/usr/bin/python3"),
    )
    assert process_platform._process_matches_hint(77778, "python") is True
    assert process_platform._process_matches_hint(77778, "other") is False

    fake_proc_root = tmp_path / "proc"
    fake_proc_root.mkdir()
    cmdline = fake_proc_root / "cmdline"
    cmdline.write_bytes(b"/opt/venv/bin/python\x00-m\x00app\x00")
    monkeypatch.setattr(
        process_platform,
        "Path",
        lambda raw: cmdline if str(raw).startswith("/proc/") else Path(raw),
    )
    assert process_platform._process_matches_hint(77778, "python") is True
    assert process_platform._process_matches_hint(77778, "llama-server") is False


def test_win32_error_falls_back_when_ctypes_lacks_winerror(monkeypatch) -> None:
    import ctypes

    class _FakeBasic(ctypes.Structure):
        _fields_ = [("LimitFlags", ctypes.c_uint32)]

    class FakeExtended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _FakeBasic)]

    fake_api = SimpleNamespace(CreateJobObjectW=lambda *_a: 0)
    monkeypatch.setattr(process_platform, "os", _fake_os("nt"))
    monkeypatch.setattr(process_platform, "_get_kernel32", lambda: (fake_api, FakeExtended))
    monkeypatch.delattr(ctypes, "WinError", raising=False)
    monkeypatch.delattr(ctypes, "get_last_error", raising=False)

    with pytest.raises(OSError, match="Win32 error 0"):
        WindowsJobObject()

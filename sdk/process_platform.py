"""OS-level subprocess tree isolation, Job Object ownership, and termination."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any

_JOB_OBJECT_EXTENDED_LIMIT_INFO = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

_KERNEL32_LOCK = threading.Lock()
_KERNEL32_API: Any | None = None
_KERNEL32_EXTENDED_STRUCT: Any | None = None


def _get_kernel32() -> tuple[Any, Any]:
    global _KERNEL32_API, _KERNEL32_EXTENDED_STRUCT
    if _KERNEL32_API is not None and _KERNEL32_EXTENDED_STRUCT is not None:
        return _KERNEL32_API, _KERNEL32_EXTENDED_STRUCT
    with _KERNEL32_LOCK:
        if _KERNEL32_API is not None and _KERNEL32_EXTENDED_STRUCT is not None:
            return _KERNEL32_API, _KERNEL32_EXTENDED_STRUCT
        import ctypes
        from ctypes import wintypes

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.TerminateProcess.restype = wintypes.BOOL
        api.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        api.QueryFullProcessImageNameW.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        _KERNEL32_API = api
        _KERNEL32_EXTENDED_STRUCT = _ExtendedLimit
        return api, _ExtendedLimit


def real_int(value: Any) -> int | None:
    """Return ``value`` if it is a positive integer (excluding ``bool``)."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def extract_process_handle(process_or_handle: Any) -> int | None:
    """Return the native Win32 handle integer from a process or handle."""
    direct = real_int(process_or_handle)
    if direct is not None:
        return direct
    return real_int(getattr(process_or_handle, "_handle", None))


def _system32_executable(name: str) -> str:
    sys_root = os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = Path(sys_root) / "System32" / name
    return str(candidate) if candidate.is_file() else name


def subprocess_isolation_kwargs(
    *,
    hide_window: bool = True,
    new_process_group: bool = False,
) -> dict[str, Any]:
    """Return OS-specific ``Popen`` kwargs that hide windows and isolate trees."""
    if os.name != "nt":
        return {"start_new_session": True}
    flags = _CREATE_NO_WINDOW if hide_window else 0
    if new_process_group:
        flags |= _CREATE_NEW_PROCESS_GROUP
    return {"creationflags": flags}


def _win32_last_error() -> int:
    import ctypes

    get_last_error = getattr(ctypes, "get_last_error", None)
    return int(get_last_error()) if callable(get_last_error) else 0


def _win32_error(err: int | None = None) -> OSError:
    import ctypes

    code = _win32_last_error() if err is None else int(err)
    win_error = getattr(ctypes, "WinError", None)
    if callable(win_error):
        return win_error(code)
    return OSError(code, f"Win32 error {code}")


class WindowsJobObject:
    """Windows Job Object configured with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``."""

    def __init__(self, process: Any | None = None) -> None:
        self._lock = threading.Lock()
        self._handle: int | None = None
        if os.name != "nt":
            return
        if process is None:
            self._ensure_created()
            return
        if extract_process_handle(process) is not None and not self.assign(process):
            err = _win32_last_error()
            self.close()
            raise _win32_error(err)

    def _ensure_created(self) -> int | None:
        if os.name != "nt":
            return None
        if self._handle is not None:
            return self._handle
        import ctypes

        api, extended_cls = _get_kernel32()
        handle = api.CreateJobObjectW(None, None)
        if not handle:
            raise _win32_error()
        limits = extended_cls()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = api.SetInformationJobObject(
            handle, _JOB_OBJECT_EXTENDED_LIMIT_INFO, ctypes.byref(limits), ctypes.sizeof(limits),
        )
        if not ok:
            err = _win32_last_error()
            api.CloseHandle(handle)
            raise _win32_error(err)
        self._handle = int(handle)
        return self._handle

    def assign(self, process_or_handle: Any) -> bool:
        """Assign a process (or raw Win32 handle) to this Job Object."""
        if os.name != "nt":
            return False
        raw_handle = extract_process_handle(process_or_handle)
        if raw_handle is None:
            return False
        with self._lock:
            try:
                job_handle = self._ensure_created()
            except OSError:
                return False
            if not job_handle:
                return False
            from ctypes import wintypes

            api, _ = _get_kernel32()
            return bool(api.AssignProcessToJobObject(wintypes.HANDLE(job_handle), wintypes.HANDLE(raw_handle)))

    def close(self) -> None:
        if os.name != "nt":
            return
        with self._lock:
            handle = self._handle
            self._handle = None
        if handle:
            try:
                api, _ = _get_kernel32()
                api.CloseHandle(handle)
            except Exception:
                pass


def is_pid_alive(pid: int) -> bool:
    """Return True if ``pid`` is a live OS process."""
    if pid <= 0:
        return False
    if os.name == "nt":
        api, _ = _get_kernel32()
        handle = api.OpenProcess(_SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        try:
            return int(api.WaitForSingleObject(handle, 0)) == _WAIT_TIMEOUT
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _query_process_name_or_cmdline(pid: int) -> str:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        api, _ = _get_kernel32()
        handle = api.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if api.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            api.CloseHandle(handle)
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    try:
        if proc_cmdline.is_file():
            return proc_cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
    except OSError:
        pass
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=1.0, check=False,
        )
        return res.stdout.strip()
    except OSError:
        return ""


def _process_matches_hint(pid: int, hint: str) -> bool:
    clean = str(hint or "").strip().lower()
    if not clean:
        return True
    desc = _query_process_name_or_cmdline(pid).strip().lower()
    if not desc:
        return True
    return clean in desc


def _run_taskkill(pid: int, *, force: bool, timeout: float = 2.5) -> None:
    args = [_system32_executable("taskkill.exe"), "/T"]
    if force:
        args.append("/F")
    args.extend(["/PID", str(pid)])
    try:
        subprocess.run(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
            timeout=max(0.5, float(timeout)),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def terminate_process_tree(
    proc: Any,
    *,
    timeout: float = 3.0,
    job: WindowsJobObject | None = None,
) -> None:
    """Gracefully terminate ``proc`` and its descendants, escalating to forced kill."""
    if proc is None:
        if job is not None:
            job.close()
        return
    poll_fn = getattr(proc, "poll", None)
    if callable(poll_fn) and poll_fn() is not None:
        if job is not None:
            job.close()
        return

    wait_budget = max(0.2, float(timeout))
    pid = real_int(getattr(proc, "pid", None))
    has_real_handle = extract_process_handle(proc) is not None

    if os.name == "nt":
        try:
            proc.terminate()
            proc.wait(timeout=wait_budget)
        except Exception:
            pass
        still_running = callable(poll_fn) and poll_fn() is None
        if still_running and job is not None:
            job.close()
            job = None
            try:
                proc.wait(timeout=0.5)
            except Exception:
                pass
            still_running = callable(poll_fn) and poll_fn() is None
        if still_running and has_real_handle and pid is not None:
            _run_taskkill(pid, force=True, timeout=wait_budget)
        if callable(poll_fn) and poll_fn() is None:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        if job is not None:
            job.close()
        return

    pgid: int | None = None
    if pid is not None and hasattr(os, "getpgid") and hasattr(os, "killpg"):
        try:
            resolved = int(os.getpgid(pid))
            if resolved > 1 and resolved != os.getpgrp():
                pgid = resolved
        except OSError:
            pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=wait_budget)
    except Exception:
        pass
    if callable(poll_fn) and poll_fn() is None:
        sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            if pgid is not None:
                os.killpg(pgid, sigkill)
            else:
                proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass
    if job is not None:
        job.close()


def _wait_pid_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.05, float(timeout))
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(0.05)
    return not is_pid_alive(pid)


def terminate_pid(
    pid: int,
    *,
    pgid: int | None = None,
    timeout: float = 3.0,
    expected_name_hint: str = "",
) -> bool:
    """Terminate an external detached PID / process group safely."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return True
    if pid == os.getpid() or pid == os.getppid():
        return False
    if not is_pid_alive(pid):
        return True
    if not _process_matches_hint(pid, expected_name_hint):
        return False

    wait_budget = max(0.2, float(timeout))
    if os.name == "nt":
        _run_taskkill(pid, force=False, timeout=min(wait_budget, 1.5))
        if _wait_pid_exit(pid, min(wait_budget, 0.8)):
            return True
        _run_taskkill(pid, force=True, timeout=wait_budget)
        if _wait_pid_exit(pid, 0.8):
            return True
        api, _ = _get_kernel32()
        handle = api.OpenProcess(_PROCESS_TERMINATE, False, int(pid))
        if handle:
            try:
                api.TerminateProcess(handle, 1)
            finally:
                api.CloseHandle(handle)
        return _wait_pid_exit(pid, 0.5)

    use_pgid = (
        isinstance(pgid, int)
        and not isinstance(pgid, bool)
        and pgid > 1
        and hasattr(os, "killpg")
        and pgid != os.getpgrp()
    )
    try:
        if use_pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    if _wait_pid_exit(pid, min(wait_budget, 2.0)):
        return True
    sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
    try:
        if use_pgid:
            os.killpg(pgid, sigkill)
        else:
            os.kill(pid, sigkill)
    except OSError:
        pass
    return _wait_pid_exit(pid, 0.8)


__all__ = [
    "WindowsJobObject",
    "extract_process_handle",
    "is_pid_alive",
    "real_int",
    "subprocess_isolation_kwargs",
    "terminate_pid",
    "terminate_process_tree",
]

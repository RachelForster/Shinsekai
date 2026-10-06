"""Hidden child process, protocol handshake and ownership of its process tree."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence

from core.paths import source_root
from core.agent.ipc import JsonRpcPeer, fault
from sdk.agent import (
    AGENT_PROTOCOL_VERSION,
    AGENT_EVENT_SCHEMA_VERSION,
    AgentBackendConfig,
    AgentBackendDescriptor,
)


class _WindowsJob:
    def __init__(self, process: subprocess.Popen) -> None:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
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

        class Counters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", Counters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ) or not self.api.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(process._handle))
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class AgentWorkerSupervisor:
    def __init__(
        self,
        config: AgentBackendConfig,
        *,
        handler: Callable[[str, dict], object],
        notification: Callable[[str, dict], None],
        command: Sequence[str] | None = None,
    ) -> None:
        self.config, self.handler, self.notification = config, handler, notification
        self.command = tuple(
            command or (sys.executable, "-m", "application.agent.worker")
        )
        self.process: subprocess.Popen | None = None
        self.peer: JsonRpcPeer | None = None
        self.job: _WindowsJob | None = None
        self.stderr: deque[str] = deque(maxlen=64)
        self.opened_sessions: set[str] = set()

    def start(self) -> AgentBackendDescriptor:
        if self.process is not None:
            raise RuntimeError("Worker must be stopped before starting another")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(source_root()) + os.pathsep + env.get("PYTHONPATH", "")
        flags = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=source_root(),
            env=env,
            **flags,
        )
        try:
            if os.name == "nt":
                self.job = _WindowsJob(self.process)
            process = self.process

            def drain() -> None:
                while body := process.stderr.readline(8192):
                    self.stderr.append(body.decode("utf-8", errors="replace"))

            threading.Thread(target=drain, name="agent-stderr", daemon=True).start()
            self.peer = JsonRpcPeer(
                process.stdout,
                process.stdin,
                prefix="h",
                handler=self.handler,
                notification=self.notification,
            )
            self.peer.start()
            response = self.peer.request(
                "worker.initialize",
                {
                    "protocolVersion": AGENT_PROTOCOL_VERSION,
                    "eventSchemaVersion": AGENT_EVENT_SCHEMA_VERSION,
                    "config": self.config.to_wire(),
                },
            )
            if not isinstance(response, dict):
                raise fault("PROTOCOL_MISMATCH", "Invalid worker handshake response")
            if (
                str(response.get("protocolVersion", "")).split(".")[0]
                != AGENT_PROTOCOL_VERSION.split(".")[0]
                or type(response.get("eventSchemaVersion")) is not int
                or response.get("eventSchemaVersion") != AGENT_EVENT_SCHEMA_VERSION
            ):
                raise fault("PROTOCOL_MISMATCH", "Worker handshake is incompatible")
            descriptor = AgentBackendDescriptor.model_validate(response["backend"])
            if (descriptor.backend_id, descriptor.version) != (
                self.config.backend_id,
                self.config.backend_version,
            ) or descriptor.availability != "ready":
                raise fault(
                    "PROTOCOL_MISMATCH", "Worker reported a different backend binding"
                )
            return descriptor
        except BaseException:
            self.stop(force=True)
            raise

    def stop(self, *, force: bool = False) -> None:
        process, peer = self.process, self.peer
        if process is None:
            return
        if not force and peer and not peer.failure and process.poll() is None:
            try:
                peer.request("worker.shutdown", {}, timeout=1)
                process.wait(timeout=1)
            except Exception:
                pass
        if peer:
            peer.close()
        if self.job:
            self.job.close()
            self.job = None
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        self.process, self.peer = None, None
        self.opened_sessions.clear()

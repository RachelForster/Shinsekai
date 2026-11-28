"""Hidden child process, protocol handshake and ownership of its process tree."""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence

from core.paths import source_root
from core.agent.ipc import JsonRpcPeer, fault
from sdk.agent import (
    AGENT_PROTOCOL_VERSION,
    AGENT_EVENT_SCHEMA_VERSION,
    AgentBackendConfig,
    AgentBackendDescriptor,
)
from sdk.process_guard import WindowsJobObject


class AgentWorkerSupervisor:
    def __init__(
        self,
        config: AgentBackendConfig,
        *,
        handler: Callable[[str, dict], object],
        notification: Callable[[str, dict], None],
        command: Sequence[str] | None = None,
        environment: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self.config, self.handler, self.notification = config, handler, notification
        self.environment = environment
        self.command = tuple(
            command or (sys.executable, "-m", "application.agent.worker")
        )
        self.process: subprocess.Popen | None = None
        self.peer: JsonRpcPeer | None = None
        self.job: WindowsJobObject | None = None
        self.stderr: deque[str] = deque(maxlen=64)
        self.opened_sessions: set[str] = set()

    def start(self) -> AgentBackendDescriptor:
        if self.process is not None:
            raise RuntimeError("Worker must be stopped before starting another")
        env = os.environ.copy()
        if self.environment:
            env.update(self.environment())
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
                self.job = WindowsJobObject(self.process)
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
            try:
                stream.close()
            except OSError as error:
                # Closing buffered stdin may flush an RPC reply after the child
                # exits. This is expected during termination, like communicate().
                if stream is not process.stdin or not (
                    error.errno == errno.EPIPE
                    or (os.name == "nt" and error.errno == errno.EINVAL)
                ):
                    raise
        self.process, self.peer = None, None
        self.opened_sessions.clear()

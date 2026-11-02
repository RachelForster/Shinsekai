"""Private worker entry point. stdout is exclusively JSON-RPC, never logging."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from core.agent.ipc import JsonRpcPeer, fault
from sdk.agent import (
    AGENT_EVENT_SCHEMA_VERSION,
    AGENT_PROTOCOL_VERSION,
    AgentBackend,
    AgentBackendConfig,
    AgentBackendEvent,
    AgentError,
    AgentHostToolCall,
    AgentHostToolResult,
    AgentInputAnswer,
    AgentInputRequest,
    AgentSessionConfig,
    AgentTaskCompletion,
    AgentTaskExecution,
    AgentRequestError,
)


class _HostPort:
    def __init__(self, peer: JsonRpcPeer, task: AgentTaskExecution) -> None:
        self.peer, self.task = peer, task

    async def invoke_tool(self, request: AgentHostToolCall) -> AgentHostToolResult:
        result = await asyncio.to_thread(
            self.peer.request,
            "host.tools.invoke",
            {
                "taskId": self.task.task_id,
                "attemptId": self.task.attempt_id,
                "call": request.to_wire(),
            },
            timeout=3600,
        )
        return AgentHostToolResult.model_validate(result)

    async def request_input(self, request: AgentInputRequest) -> AgentInputAnswer:
        result = await asyncio.to_thread(
            self.peer.request,
            "host.input.request",
            {
                "taskId": self.task.task_id,
                "attemptId": self.task.attempt_id,
                "request": request.to_wire(),
            },
            timeout=3600,
        )
        return AgentInputAnswer.model_validate(result)


class Worker:
    def __init__(self) -> None:
        self.backend: AgentBackend | None = None
        self.sessions = {}
        self.active: asyncio.Task | None = None
        self.attempt_id: str | None = None
        self.loop = asyncio.new_event_loop()
        self.stop = threading.Event()
        self.peer = JsonRpcPeer(
            sys.stdin.buffer,
            sys.stdout.buffer,
            prefix="w",
            handler=self.handle,
            notification=self.notification,
        )
        self._loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def notification(self, method: str, params: dict) -> None:
        raise ValueError("Worker does not accept RPC notifications")

    def handle(self, method: str, params: dict) -> object:
        if method == "worker.ping":
            return {"ready": self.backend is not None}
        return asyncio.run_coroutine_threadsafe(
            self._handle(method, params), self.loop
        ).result(timeout=5)

    async def _handle(self, method: str, params: dict) -> object:
        if method == "worker.initialize":
            if self.backend is not None:
                raise fault("INVALID_REQUEST", "Worker is already initialized")
            if (
                str(params.get("protocolVersion", "")).split(".")[0]
                != AGENT_PROTOCOL_VERSION.split(".")[0]
                or type(params.get("eventSchemaVersion")) is not int
                or params.get("eventSchemaVersion") != AGENT_EVENT_SCHEMA_VERSION
            ):
                raise fault(
                    "PROTOCOL_MISMATCH", "Agent protocol version is incompatible"
                )
            config = AgentBackendConfig.model_validate(params["config"])
            # Explicit registration. No backend implementation is imported by the host.
            from ai.agent.backends.mock import MockAgentBackend
            from ai.agent.backends.pi import PiAgentBackend

            factories = {"mock": MockAgentBackend, "pi": PiAgentBackend}
            if config.backend_id not in factories or config.backend_version != "1":
                raise fault(
                    "BACKEND_UNAVAILABLE",
                    "Requested backend is not registered in this worker",
                )
            self.backend = factories[config.backend_id]()
            descriptor = await self.backend.initialize(config)
            return {
                "protocolVersion": AGENT_PROTOCOL_VERSION,
                "eventSchemaVersion": AGENT_EVENT_SCHEMA_VERSION,
                "backend": descriptor.to_wire(),
            }
        if self.backend is None:
            raise fault("BACKEND_UNAVAILABLE", "Worker has not been initialized")
        if method == "session.open":
            config = AgentSessionConfig.model_validate(params)
            if config.session_id not in self.sessions:
                self.sessions[config.session_id] = await self.backend.open_session(
                    config
                )
            return {"sessionId": config.session_id}
        if method == "session.close":
            if self.active is not None:
                raise fault("SESSION_BUSY", "A task is still executing")
            session = self.sessions.pop(params["sessionId"], None)
            if session is not None:
                await self.backend.close_session(session)
            return None
        if method == "task.start":
            if self.active is not None:
                raise fault("SESSION_BUSY", "Worker already has an active task")
            task = AgentTaskExecution.model_validate(params)
            if task.request.session_id not in self.sessions:
                raise fault("INVALID_REQUEST", "Agent session is not open")
            self.attempt_id = task.attempt_id
            self.active = asyncio.create_task(self._run(task))
            return {"accepted": True}
        if method == "task.cancel":
            if self.active is not None and params["attemptId"] == self.attempt_id:
                active = self.active
                await self.backend.cancel(self.attempt_id)
                active.cancel()
            return {"accepted": True}
        if method == "task.respond":
            answer = AgentInputAnswer.model_validate(params["answer"])
            await self.backend.respond(answer.input_request_id, answer)
            return None
        if method == "worker.shutdown":
            if self.active is not None:
                self.active.cancel()
                await self.active
            await self.backend.shutdown()
            self.stop.set()
            return None
        raise fault("INVALID_REQUEST", "Unknown Agent worker method")

    async def _run(self, task: AgentTaskExecution) -> None:
        seq = 0
        completion = None
        try:
            async for event in self.backend.run(
                self.sessions[task.request.session_id], task, _HostPort(self.peer, task)
            ):
                if event.attempt_id != task.attempt_id or event.worker_seq <= seq:
                    raise fault("PROTOCOL_MISMATCH", "Invalid backend event sequence")
                seq = event.worker_seq
                if completion is not None:
                    raise fault(
                        "PROTOCOL_MISMATCH",
                        "Backend produced output after task completion",
                    )
                if event.type == "task.completed":
                    # Do not publish completion while the generator can still work.
                    completion = event.payload
                else:
                    self.peer.notify(
                        "task.event", {"taskId": task.task_id, "event": event.to_wire()}
                    )
            if completion is None:
                raise fault(
                    "PROTOCOL_MISMATCH", "Backend ended without task completion"
                )
        except asyncio.CancelledError:
            completion = AgentTaskCompletion(status="cancelled")
        except Exception as exc:
            error = (
                exc.error
                if isinstance(exc, AgentRequestError)
                else AgentError(
                    code="BACKEND_UNAVAILABLE",
                    message="Agent backend execution failed",
                )
            )
            completion = AgentTaskCompletion(status="failed", error=error)
        finally:
            self.active, self.attempt_id = None, None
        event = AgentBackendEvent(
            attempt_id=task.attempt_id,
            worker_seq=seq + 1,
            timestamp=datetime.now(timezone.utc),
            type="task.completed",
            payload=completion,
        )
        self.peer.notify(
            "task.event", {"taskId": task.task_id, "event": event.to_wire()}
        )

    def run(self) -> int:
        self._loop_thread.start()
        self.peer.start()
        try:
            while not self.stop.wait(0.05) and not self.peer.failure:
                pass
        finally:
            # Give the shutdown response a chance to reach the private pipe.
            time.sleep(0.05)
            self.peer.close()

            async def cleanup() -> None:
                active = self.active
                if active is not None:
                    active.cancel()
                    await asyncio.gather(active, return_exceptions=True)
                if self.backend is not None and not self.stop.is_set():
                    await self.backend.shutdown()
                await self.loop.shutdown_asyncgens()

            try:
                asyncio.run_coroutine_threadsafe(cleanup(), self.loop).result(timeout=2)
            except Exception:
                pass  # The process owner still enforces termination of the tree.
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._loop_thread.join(timeout=1)
            if os.name != "nt" and os.getpgrp() == os.getpid():
                # A supervisor-owned session also cleans descendants after the
                # host disappears. Never signal the group of a directly run CLI.
                os.killpg(os.getpid(), signal.SIGKILL)
        return 0


if __name__ == "__main__":
    raise SystemExit(Worker().run())

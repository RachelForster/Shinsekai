"""Pi's private JSONL protocol (distinct from the host JSON-RPC protocol)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from collections import deque
from pathlib import Path

from core.agent.ipc import fault
from sdk.logging.redaction import redact_text

MAX_PI_FRAME = 1024 * 1024


class PiRpcProcess:
    def __init__(self, command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        self.command, self.cwd, self.env = command, cwd, env
        self.process = None
        self.pending = {}
        self.events = asyncio.Queue(maxsize=256)
        self.stderr = deque(maxlen=32)
        self.failure = None
        self._closing = False
        self._write_lock, self._close_lock = asyncio.Lock(), asyncio.Lock()
        self._readers = []

    async def start(self) -> None:
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=self.cwd,
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MAX_PI_FRAME,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {}
                ),
            )
        except OSError as exc:
            raise fault("BACKEND_UNAVAILABLE", "Pi executable could not start") from exc
        self._readers = [
            asyncio.create_task(self._read()),
            asyncio.create_task(self._drain_stderr()),
        ]

    def _fail(self, error) -> None:
        if self.failure or self._closing:
            return
        self.failure = error
        for _, future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        while self.events.full():
            self.events.get_nowait()
        self.events.put_nowait({"type": "_failure"})

    async def _read(self) -> None:
        try:
            while body := await self.process.stdout.readline():
                if len(body) > MAX_PI_FRAME or not body.endswith(b"\n"):
                    raise ValueError("Invalid Pi frame")
                record = json.loads(
                    body.decode("utf-8"),
                    parse_constant=lambda _: (_ for _ in ()).throw(
                        ValueError("Nonfinite JSON")
                    ),
                )
                if not isinstance(record, dict) or not isinstance(
                    record.get("type"), str
                ):
                    raise ValueError("Invalid Pi record")
                if record["type"] == "response":
                    binding = self.pending.get(record.get("id"))
                    if binding:
                        kind, future = binding
                        if (
                            record.get("command") != kind
                            or type(record.get("success")) is not bool
                        ):
                            raise ValueError("Invalid Pi response")
                        if not future.done():
                            future.set_result(record)
                    elif record.get("command") == "parse":
                        raise ValueError("Pi rejected protocol input")
                else:
                    self.events.put_nowait(record)
            self._fail(fault("WORKER_LOST", "Pi exited before execution settled"))
        except asyncio.CancelledError:
            pass
        except asyncio.QueueFull:
            self._fail(fault("LIMIT_EXCEEDED", "Pi event buffer exceeded its limit"))
        except Exception:
            self._fail(fault("PROTOCOL_MISMATCH", "Invalid Pi protocol output"))

    async def _drain_stderr(self) -> None:
        while body := await self.process.stderr.read(8192):
            text = body.decode("utf-8", errors="replace")
            secret = self.env.get("SHINSEKAI_PI_API_KEY", "")
            if secret:
                text = text.replace(secret, "[REDACTED]")
            self.stderr.append(redact_text(text))

    async def send(self, record: dict) -> None:
        if self.failure:
            raise self.failure
        body = (
            json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
            + b"\n"
        )
        if len(body) > MAX_PI_FRAME:
            raise fault("LIMIT_EXCEEDED", "Pi input exceeds the protocol frame limit")
        async with self._write_lock:
            try:
                self.process.stdin.write(body)
                await self.process.stdin.drain()
            except (OSError, RuntimeError) as exc:
                raise fault("WORKER_LOST", "Pi protocol pipe closed") from exc

    async def request(self, kind: str, *, timeout: float = 10, **payload):
        if len(self.pending) >= 32:
            raise fault("LIMIT_EXCEEDED", "Too many Pi protocol requests")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = kind, future
        try:
            await self.send({"id": request_id, "type": kind, **payload})
            response = await asyncio.wait_for(future, timeout)
            if not response["success"]:
                # Native error strings may contain provider credentials or HTTP payloads.
                raise fault("BACKEND_UNAVAILABLE", f"Pi rejected the {kind} command")
            return response.get("data")
        except asyncio.TimeoutError as exc:
            raise fault(
                "WORKER_LOST", "Pi command did not respond before its deadline"
            ) from exc
        finally:
            self.pending.pop(request_id, None)
            if future.done() and not future.cancelled():
                future.exception()

    async def next_event(self) -> dict:
        record = await self.events.get()
        if record["type"] == "_failure":
            raise self.failure
        return record

    async def close(self) -> None:
        async with self._close_lock:
            if self._closing:
                return
            self._closing = True
            if self.process and self.process.returncode is None:
                self.process.stdin.close()
                try:
                    await asyncio.wait_for(self.process.wait(), 0.5)
                except asyncio.TimeoutError:
                    try:
                        self.process.kill()
                    except ProcessLookupError:
                        pass
                    await self.process.wait()
            for reader in self._readers:
                reader.cancel()
            await asyncio.gather(*self._readers, return_exceptions=True)
            for _, future in self.pending.values():
                if not future.done():
                    future.set_exception(fault("WORKER_LOST", "Pi process was closed"))

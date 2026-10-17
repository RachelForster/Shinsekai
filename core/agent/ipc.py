"""Bounded, bidirectional JSON-RPC 2.0 over private UTF-8 JSONL pipes."""

from __future__ import annotations

import json
import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from typing import BinaryIO, Callable

from sdk.agent import AgentError, AgentRequestError

MAX_FRAME_BYTES = 1024 * 1024


def fault(code: str, message: str) -> AgentRequestError:
    return AgentRequestError(AgentError(code=code, message=message))


def encode_frame(frame: dict) -> bytes:
    body = (
        json.dumps(
            frame, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    if len(body) > MAX_FRAME_BYTES:
        raise fault("PROTOCOL_MISMATCH", "Agent IPC frame exceeds 1 MiB")
    return body


def decode_frame(body: bytes) -> dict:
    def invalid_constant(value: str) -> None:
        raise ValueError(f"Non-JSON number: {value}")

    if not body.endswith(b"\n") or len(body) > MAX_FRAME_BYTES:
        raise ValueError("Incomplete or oversized Agent IPC frame")
    value = json.loads(body.decode("utf-8"), parse_constant=invalid_constant)
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        raise ValueError("Expected a JSON-RPC 2.0 object")
    if "method" in value:
        if not isinstance(value["method"], str) or not isinstance(
            value.get("params", {}), dict
        ):
            raise ValueError("Invalid Agent RPC request")
        if "result" in value or "error" in value:
            raise ValueError("Request cannot contain a response")
    elif ("result" in value) == ("error" in value) or "id" not in value:
        raise ValueError("Expected one RPC result or error")
    if "id" in value and (not isinstance(value["id"], str) or not value["id"]):
        raise ValueError("Agent RPC ID must be a nonempty string")
    return value


class JsonRpcPeer:
    """Keep reading while handlers wait for tools or user input.

    Pending RPCs, handler jobs and outgoing frames are bounded. Protocol faults
    fail every waiter; the supervisor owns process termination and recovery.
    """

    def __init__(
        self,
        reader: BinaryIO,
        writer: BinaryIO,
        *,
        prefix: str,
        handler: Callable[[str, dict], object],
        notification: Callable[[str, dict], None],
    ) -> None:
        self.reader, self.writer = reader, writer
        self.prefix, self.handler, self.notification = prefix, handler, notification
        self.failure: AgentRequestError | None = None
        self._lock = threading.Lock()
        self._counter = 0
        self._pending: dict[str, Future] = {}
        self._outgoing: queue.Queue[bytes] = queue.Queue(maxsize=128)
        self._slots = threading.BoundedSemaphore(16)
        self._pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="agent-rpc-handler"
        )
        self._stopped = threading.Event()
        self._reader_thread = threading.Thread(
            target=self._read, name="agent-rpc-reader", daemon=True
        )
        self._writer_thread = threading.Thread(
            target=self._write, name="agent-rpc-writer", daemon=True
        )

    def start(self) -> None:
        self._writer_thread.start()
        self._reader_thread.start()

    def send(self, frame: dict) -> None:
        if self.failure:
            raise self.failure
        try:
            self._outgoing.put(encode_frame(frame), timeout=2)
        except queue.Full:
            self._fail(fault("PROTOCOL_MISMATCH", "Agent IPC output queue is full"))
            raise self.failure

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, *, timeout: float = 5) -> object:
        with self._lock:
            if self.failure:
                raise self.failure
            if len(self._pending) >= 64:
                raise fault("LIMIT_EXCEEDED", "Too many pending Agent RPC requests")
            self._counter += 1
            rpc_id = f"{self.prefix}-{self._counter}"
            future: Future = Future()
            self._pending[rpc_id] = future
        try:
            self.send(
                {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
            )
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            raise fault("WORKER_LOST", "Agent RPC request timed out") from exc
        finally:
            with self._lock:
                self._pending.pop(rpc_id, None)

    def _fail(self, error: AgentRequestError) -> None:
        with self._lock:
            if self.failure:
                return
            self.failure = error
            self._stopped.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)

    def _read(self) -> None:
        try:
            while not self._stopped.is_set():
                body = self.reader.readline(MAX_FRAME_BYTES + 1)
                if not body:
                    raise EOFError("Agent IPC closed")
                frame = decode_frame(body)
                if "method" not in frame:
                    if not frame["id"].startswith(self.prefix + "-"):
                        raise ValueError("RPC response has the wrong direction")
                    with self._lock:
                        future = self._pending.get(frame["id"])
                        if future and not future.done():
                            if "error" in frame:
                                error = frame["error"]
                                if (
                                    not isinstance(error, dict)
                                    or type(error.get("code")) is not int
                                ):
                                    raise ValueError("Invalid RPC error")
                                future.set_exception(
                                    AgentRequestError(
                                        AgentError.model_validate(error["data"])
                                    )
                                )
                            else:
                                future.set_result(frame["result"])
                elif "id" not in frame:
                    self.notification(frame["method"], frame.get("params", {}))
                else:
                    if frame["id"].startswith(
                        self.prefix + "-"
                    ) or not self._slots.acquire(blocking=False):
                        raise ValueError(
                            "Invalid RPC direction or handler queue overflow"
                        )
                    self._pool.submit(self._handle, frame)
        except (OSError, EOFError) as exc:
            self._fail(fault("WORKER_LOST", str(exc) or "Agent IPC closed"))
        except Exception:
            self._fail(fault("PROTOCOL_MISMATCH", "Invalid Agent IPC message"))

    def _handle(self, frame: dict) -> None:
        try:
            try:
                result = self.handler(frame["method"], frame.get("params", {}))
                response = {"jsonrpc": "2.0", "id": frame["id"], "result": result}
            except Exception as exc:
                error = (
                    exc.error
                    if isinstance(exc, AgentRequestError)
                    else AgentError(
                        code="INVALID_REQUEST", message="Agent RPC request was rejected"
                    )
                )
                response = {
                    "jsonrpc": "2.0",
                    "id": frame["id"],
                    "error": {
                        "code": -32000,
                        "message": error.message,
                        "data": error.to_wire(),
                    },
                }
            self.send(response)
        except AgentRequestError as exc:
            self._fail(exc)
        except Exception:
            self._fail(fault("WORKER_LOST", "Unable to reply to Agent RPC request"))
        finally:
            self._slots.release()

    def _write(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    body = self._outgoing.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.writer.write(body)
                self.writer.flush()
        except (OSError, ValueError):
            self._fail(fault("WORKER_LOST", "Unable to write Agent IPC message"))

    def close(self) -> None:
        self._fail(fault("WORKER_LOST", "Agent IPC was closed"))
        self._pool.shutdown(wait=False, cancel_futures=True)

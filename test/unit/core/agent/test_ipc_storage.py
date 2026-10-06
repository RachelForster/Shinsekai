from __future__ import annotations

import json
import os
import sqlite3
import sys
import time

import pytest

from application.agent.supervise_worker import AgentWorkerSupervisor
from core.agent.ipc import MAX_FRAME_BYTES, decode_frame, encode_frame
from core.agent.storage import AgentStore
from sdk.agent import AgentBackendConfig, AgentRequestError


@pytest.mark.parametrize(
    "body",
    [
        b"not json\n",
        b"[]\n",
        b'{"jsonrpc":"1.0","id":"h-1","result":null}\n',
        b'{"jsonrpc":"2.0","id":true,"result":null}\n',
        b'{"jsonrpc":"2.0","id":"h-1","result":NaN}\n',
        b'{"jsonrpc":"2.0","id":"h-1","result":null,"error":{}}\n',
        b'{"jsonrpc":"2.0","id":"h-1","result":null}',
        b"x" * (MAX_FRAME_BYTES + 1),
    ],
    ids=[
        "not-json",
        "batch",
        "version",
        "boolean-id",
        "nan",
        "two-responses",
        "no-newline",
        "oversized",
    ],
)
def test_invalid_jsonl_or_rpc_frames_are_rejected(body):
    with pytest.raises((ValueError, UnicodeError)):
        decode_frame(body)


def test_frame_is_utf8_json_and_has_a_hard_size_bound():
    frame = {
        "jsonrpc": "2.0",
        "id": "h-1",
        "method": "test",
        "params": {"text": "新世界"},
    }
    assert decode_frame(encode_frame(frame)) == frame
    with pytest.raises(AgentRequestError):
        encode_frame({**frame, "params": {"text": "x" * MAX_FRAME_BYTES}})


def test_database_lease_and_rollback_protect_single_state_owner(tmp_path):
    path = tmp_path / "agent.sqlite"
    store = AgentStore(path)
    try:
        with pytest.raises(RuntimeError, match="already has an owner"):
            AgentStore(path)
        with pytest.raises(ValueError):
            with store.transaction():
                store.put("task", "one", {"value": 1})
                store.append_event("one", {"type": "test"})
                raise ValueError("rollback")
        assert store.get("task", "one") is None
        assert not store.read_events("one", 0, 10)
    finally:
        store.close()
    reopened = AgentStore(path)
    reopened.close()


def test_newer_database_schema_is_preserved_and_rejected(tmp_path):
    path = tmp_path / "agent.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="schema"):
        AgentStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


@pytest.mark.parametrize("response", ["incompatible", "invalid-json", "eof"])
def test_bad_worker_handshake_is_rejected_and_its_process_is_cleaned_up(response):
    script = r"""
import json, sys, time
request = json.loads(sys.stdin.buffer.readline())
mode = sys.argv[1]
if mode == "invalid-json":
    print("protocol pollution", flush=True)
elif mode == "incompatible":
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {
        "protocolVersion": "9.0", "eventSchemaVersion": 1, "backend": {}}}), flush=True)
else:
    sys.exit(0)
time.sleep(20)
"""
    supervisor = AgentWorkerSupervisor(
        AgentBackendConfig(backend_id="mock", backend_version="1"),
        handler=lambda *args: None,
        notification=lambda *args: None,
        command=(sys.executable, "-c", script, response),
    )
    with pytest.raises(AgentRequestError) as failure:
        supervisor.start()
    assert failure.value.error.code == (
        "WORKER_LOST" if response == "eof" else "PROTOCOL_MISMATCH"
    )
    assert supervisor.process is None


def test_supervisor_terminates_worker_descendants(tmp_path):
    marker = tmp_path / "child.pid"
    script = r"""
import json, subprocess, sys, os
from pathlib import Path
request = json.loads(sys.stdin.buffer.readline())
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
Path(sys.argv[1]).write_text(str(child.pid), encoding="ascii")
print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {
    "protocolVersion": "1.0", "eventSchemaVersion": 1,
    "backend": {"backendId": "mock", "version": "1", "availability": "ready"}}}), flush=True)
sys.stdin.buffer.read()
"""
    supervisor = AgentWorkerSupervisor(
        AgentBackendConfig(backend_id="mock", backend_version="1"),
        handler=lambda *args: None,
        notification=lambda *args: None,
        command=(sys.executable, "-c", script, str(marker)),
    )
    try:
        supervisor.start()
        child_pid = int(marker.read_text(encoding="ascii"))
    finally:
        supervisor.stop(force=True)

    def alive():
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            api.OpenProcess.restype = wintypes.HANDLE
            api.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = api.OpenProcess(0x1000, False, child_pid)
            if not handle:
                return False
            code = wintypes.DWORD()
            try:
                return (
                    bool(api.GetExitCodeProcess(handle, ctypes.byref(code)))
                    and code.value == 259
                )
            finally:
                api.CloseHandle(handle)
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return False
        from pathlib import Path

        stat = Path(f"/proc/{child_pid}/stat")
        return not stat.exists() or stat.read_text().split(")", 1)[1].split()[0] != "Z"

    deadline = time.monotonic() + 5
    while alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not alive()

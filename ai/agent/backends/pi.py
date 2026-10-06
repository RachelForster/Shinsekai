"""Backend adapter for the pinned official Pi executable, loaded only in a worker."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai.agent.backends.pi_rpc import PiRpcProcess, MAX_PI_FRAME
from core.agent.ipc import fault
from core.agent.pi_runtime import PI_VERSION
from core.paths import resource_path
from sdk.agent import (
    AgentBackendCapabilities,
    AgentBackendConfig,
    AgentBackendDescriptor,
    AgentBackendEvent,
    AgentHostToolCall,
    AgentHostToolResult,
    AgentInputOption,
    AgentInputRequest,
    AgentRequestError,
    AgentResult,
    AgentSessionConfig,
    AgentTaskCompletion,
    AgentUsage,
)


@dataclass
class _Session:
    config: AgentSessionConfig
    root: Path
    model: dict
    marker: dict


class PiAgentBackend:
    def __init__(self) -> None:
        self.config = None
        self.rpc = None
        self.active_attempt = None
        self.cancelled_attempt = None

    async def initialize(self, config: AgentBackendConfig) -> AgentBackendDescriptor:
        if (
            config.options.get("piVersion") != PI_VERSION
            or not config.runtime_ref
            or not config.state_ref
        ):
            raise fault("BACKEND_UNAVAILABLE", "Pi runtime configuration is incomplete")
        self.executable = Path(config.runtime_ref).resolve()
        if not self.executable.is_file():
            raise fault("BACKEND_UNAVAILABLE", "Install the official Pi runtime first")
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.executable),
                "--version",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {}
                ),
            )
            try:
                body, _ = await asyncio.wait_for(process.communicate(), 3)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            if process.returncode or body.decode().strip() != PI_VERSION:
                raise ValueError("Version mismatch")
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Pi version probe failed (%s): %s", type(exc).__name__, exc
            )
            raise fault(
                "CAPABILITY_UNSUPPORTED",
                "Pi executable version does not match the pinned adapter",
            ) from exc
        self.config = config
        return AgentBackendDescriptor(
            backend_id="pi",
            version=config.backend_version,
            availability="ready",
            capabilities=AgentBackendCapabilities(
                host_tools=True,
                tool_policy_enforcement=True,
                streaming_text=True,
                interactive_input=True,
                native_session_resume=True,
                usage_reporting=True,
            ),
        )

    async def open_session(self, config: AgentSessionConfig):
        if (config.backend_id, config.backend_version) != (
            self.config.backend_id,
            self.config.backend_version,
        ):
            raise fault(
                "SESSION_BACKEND_MISMATCH", "Session belongs to a different backend"
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", config.session_id):
            raise fault("INVALID_REQUEST", "Invalid Pi session identifier")
        model = self.config.options.get("models", {}).get(config.model_ref)
        if not model:
            raise fault(
                "INVALID_REQUEST", "Pi model reference is not registered by the host"
            )
        root = Path(self.config.state_ref).resolve() / config.session_id
        root.mkdir(parents=True, exist_ok=True)
        snapshot = {"session": config.to_wire(), "model": model}
        marker_file = root / "binding.json"
        if marker_file.exists():
            try:
                marker = json.loads(marker_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise fault(
                    "SESSION_RESUME_UNAVAILABLE", "Pi session snapshot is unreadable"
                ) from exc
            if marker["snapshot"] != snapshot:
                raise fault(
                    "SESSION_BACKEND_MISMATCH",
                    "Pi session configuration no longer matches its snapshot",
                )
            if marker.get("hasRun") and not any((root / "native").glob("*.jsonl")):
                raise fault(
                    "SESSION_RESUME_UNAVAILABLE", "Pi session history is missing"
                )
        else:
            policy = self.config.options.get("policies", {}).get(
                config.system_policy_ref
            )
            if not policy or not Path(policy).is_file():
                raise fault(
                    "INVALID_REQUEST", "Pi system policy reference is unavailable"
                )
            text = Path(policy).read_text(encoding="utf-8")
            if len(text.encode("utf-8")) > 65536:
                raise fault("LIMIT_EXCEEDED", "Pi system policy exceeds its size limit")
            (root / "policy.md").write_text(text, encoding="utf-8")
            skills = []
            for reference in config.skill_refs:
                source = self.config.options.get("skills", {}).get(reference)
                if not source or not Path(source).is_file():
                    raise fault("INVALID_REQUEST", "Pi skill reference is unavailable")
                # Explicit trusted SKILL.md paths; support files are reached through host tools.
                target = root / (
                    "skill-"
                    + hashlib.sha256(reference.encode()).hexdigest()[:16]
                    + ".md"
                )
                target.write_text(
                    Path(source).read_text(encoding="utf-8"), encoding="utf-8"
                )
                skills.append(str(target))
            marker = {"snapshot": snapshot, "skills": skills, "hasRun": False}
            marker_file.write_text(
                json.dumps(marker, ensure_ascii=False), encoding="utf-8"
            )
        return _Session(config, root, model, marker)

    async def run(self, session: _Session, task, host):
        self.active_attempt = task.attempt_id
        token, ready = (
            secrets.token_urlsafe(32),
            asyncio.get_running_loop().create_future(),
        )
        callbacks, connections = set(), set()
        allowed = [tool.name for tool in task.tools]
        native_names = [
            "shinsekai_" + hashlib.sha256(name.encode()).hexdigest()[:24]
            for name in allowed
        ]

        async def serve(reader, writer):
            current = asyncio.current_task()
            callbacks.add(current)
            connections.add(writer)
            try:
                if len(callbacks) > 16:
                    raise ValueError("Too many host callbacks")
                body = await asyncio.wait_for(reader.readline(), 5)
                if len(body) > MAX_PI_FRAME or not body.endswith(b"\n"):
                    raise ValueError("Invalid callback frame")
                request = json.loads(body.decode("utf-8"))
                if not hmac.compare_digest(str(request.get("token", "")), token):
                    raise ValueError("Invalid callback token")
                if request.get("kind") == "ready":
                    if request.get("names") != native_names:
                        raise ValueError("Pi extension registered different tools")
                    if not ready.done():
                        ready.set_result(True)
                    result = {"ok": True}
                else:
                    call = AgentHostToolCall.model_validate(request["call"])
                    if call.name not in allowed:
                        raise fault(
                            "TOOL_DENIED", "Pi requested an unavailable host tool"
                        )
                    result = (await host.invoke_tool(call)).to_wire()
                response = (
                    json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
                    + b"\n"
                )
                if len(response) > MAX_PI_FRAME:
                    raise fault(
                        "LIMIT_EXCEEDED", "Host tool result exceeds the Pi frame limit"
                    )
                writer.write(response)
                await writer.drain()
            except AgentRequestError as exc:
                writer.write(
                    json.dumps({"ok": False, "error": exc.error.to_wire()}).encode()
                    + b"\n"
                )
                await writer.drain()
            except (
                ValueError,
                TypeError,
                AttributeError,
                KeyError,
                OSError,
                asyncio.TimeoutError,
            ):
                pass
            finally:
                callbacks.discard(current)
                connections.discard(writer)
                writer.close()
                await writer.wait_closed()

        agent_dir = session.root / "agent"
        workspace = session.root / "workspace"
        agent_dir.mkdir(exist_ok=True)
        workspace.mkdir(exist_ok=True)
        tools_file = session.root / "tools.json"
        tools_file.write_text(
            json.dumps(
                [
                    {**tool.to_wire(), "nativeName": name}
                    for tool, name in zip(task.tools, native_names)
                ]
            ),
            encoding="utf-8",
        )
        model = {
            key: value
            for key, value in session.model.items()
            if key not in ("baseUrl", "api")
        }
        (agent_dir / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "shinsekai": {
                            "baseUrl": session.model["baseUrl"],
                            "api": session.model["api"],
                            "apiKey": "$SHINSEKAI_PI_API_KEY",
                            "models": [model],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        if not env.get("SHINSEKAI_PI_API_KEY"):
            raise fault(
                "AUTH_REQUIRED", "Pi worker has no configured provider credential"
            )
        env.update(
            {
                "PI_CODING_AGENT_DIR": str(agent_dir),
                "SHINSEKAI_PI_TOOLS": str(tools_file),
                "SHINSEKAI_PI_HOST_TOKEN": token,
            }
        )
        command = [
            str(self.executable),
            "--mode",
            "rpc",
            "--provider",
            "shinsekai",
            "--model",
            model["id"],
            "--session-id",
            session.config.session_id,
            "--session-dir",
            str(session.root / "native"),
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-mcp",
            "--no-approve",
            "--no-builtin-tools",
            "--extension",
            str(resource_path("assets/agent/pi-host-tools.ts")),
            "--system-prompt",
            str(session.root / "policy.md"),
        ]
        command += ["--tools", ",".join(native_names)] if allowed else ["--no-tools"]
        for path in session.marker["skills"]:
            command += ["--skill", path]
        server = await asyncio.start_server(serve, "127.0.0.1", 0, limit=MAX_PI_FRAME)
        env["SHINSEKAI_PI_HOST_PORT"] = str(server.sockets[0].getsockname()[1])
        rpc = self.rpc = PiRpcProcess(command, cwd=workspace, env=env)
        seq, message_id, summary, stop_reason = 0, uuid.uuid4().hex, "", None
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        usage_seen = False
        submitted = False
        provider_error = ""

        def event(kind, payload):
            nonlocal seq
            seq += 1
            return AgentBackendEvent(
                attempt_id=task.attempt_id,
                worker_seq=seq,
                timestamp=datetime.now(timezone.utc),
                type=kind,
                payload=payload,
            )

        try:
            await rpc.start()
            try:
                await asyncio.wait_for(ready, 10)
            except asyncio.TimeoutError as exc:
                raise fault(
                    "BACKEND_UNAVAILABLE", "Pi host extension did not initialize"
                ) from exc
            state = await rpc.request("get_state")
            if (
                not isinstance(state, dict)
                or state.get("model", {}).get("id") != model["id"]
                or state["model"].get("provider") != "shinsekai"
            ):
                raise fault("PROTOCOL_MISMATCH", "Pi selected a different model")
            text = task.request.input.text
            for context in task.request.context:
                if context.kind != "text":
                    raise fault(
                        "CAPABILITY_UNSUPPORTED",
                        "Pi context references must be materialized by the host",
                    )
                text += "\n\n" + json.dumps(context.to_wire(), ensure_ascii=False)
            # A prompt must remain user data, including strings resembling /commands.
            text = "<shinsekai-task>\n" + text + "\n</shinsekai-task>"
            session.marker["hasRun"] = True
            (session.root / "binding.json").write_text(
                json.dumps(session.marker, ensure_ascii=False), encoding="utf-8"
            )
            submitted = True
            disposition = await rpc.request("prompt", message=text)
            if (
                not isinstance(disposition, dict)
                or disposition.get("disposition") != "started"
            ):
                raise fault("PROTOCOL_MISMATCH", "Pi did not start the submitted task")
            while True:
                record = await rpc.next_event()
                kind = record["type"]
                if (
                    kind == "message_start"
                    and record.get("message", {}).get("role") == "assistant"
                ):
                    message_id = uuid.uuid4().hex
                elif kind == "message_update":
                    update = record.get("assistantMessageEvent", {})
                    if update.get("type") == "text_delta":
                        yield event(
                            "message.delta",
                            {"messageId": message_id, "delta": update["delta"]},
                        )
                elif (
                    kind == "message_end"
                    and record.get("message", {}).get("role") == "assistant"
                ):
                    message = record["message"]
                    summary = "".join(
                        block["text"]
                        for block in message.get("content", [])
                        if block.get("type") == "text"
                    )
                    stop_reason = message.get("stopReason")
                    provider_error = str(message.get("errorMessage", ""))
                    yield event(
                        "message.completed", {"messageId": message_id, "text": summary}
                    )
                    native_usage = message.get("usage")
                    if isinstance(native_usage, dict):
                        values = [
                            native_usage.get(key)
                            for key in ("input", "output", "totalTokens")
                        ]
                        if all(type(value) is int and value >= 0 for value in values):
                            usage_seen = True
                            for key, value in zip(usage, values):
                                usage[key] += value
                            yield event("usage.updated", AgentUsage(**usage))
                elif kind == "extension_ui_request":
                    await self._input(rpc, host, record)
                elif kind == "extension_error":
                    raise fault("BACKEND_UNAVAILABLE", "Pi host extension failed")
                elif kind == "agent_settled":
                    break
            result = AgentResult(
                summary=summary, data={"usage": usage if usage_seen else None}
            )
            if stop_reason == "error":
                error_code = (
                    "AUTH_REQUIRED"
                    if any(
                        marker in provider_error.lower()
                        for marker in (
                            "401",
                            "403",
                            "api key",
                            "authentication",
                            "invalid_api_key",
                        )
                    )
                    else "BACKEND_UNAVAILABLE"
                )
                completion = AgentTaskCompletion(
                    status="failed",
                    result=result,
                    error=fault(
                        error_code,
                        (
                            "Pi provider authentication failed"
                            if error_code == "AUTH_REQUIRED"
                            else "Pi provider execution failed"
                        ),
                    ).error,
                )
            elif stop_reason == "aborted":
                completion = AgentTaskCompletion(status="cancelled", result=result)
            elif stop_reason == "stop":
                completion = AgentTaskCompletion(status="succeeded", result=result)
            else:
                raise fault(
                    "PROTOCOL_MISMATCH", "Pi settled without a final assistant response"
                )
            yield event("task.completed", completion)
        except AgentRequestError as exc:
            if self.cancelled_attempt == task.attempt_id:
                raise asyncio.CancelledError()
            if submitted and exc.error.code in ("WORKER_LOST", "PROTOCOL_MISMATCH"):
                yield event(
                    "task.completed",
                    AgentTaskCompletion(status="interrupted", error=exc.error),
                )
            else:
                raise
        finally:
            await rpc.close()
            server.close()
            await server.wait_closed()
            for writer in connections.copy():
                writer.close()
            for callback in callbacks.copy():
                callback.cancel()
            await asyncio.gather(*callbacks, return_exceptions=True)
            self.rpc, self.active_attempt = None, None

    async def _input(self, rpc, host, record):
        method = record.get("method")
        if method not in ("select", "confirm", "input", "editor"):
            return
        options = tuple(
            AgentInputOption(value=str(index), label=value)
            for index, value in enumerate(record.get("options", []))
        )
        timeout = record.get("timeout")
        request = AgentInputRequest(
            input_request_id="pi-" + record["id"],
            kind="confirmation" if method == "confirm" else "question",
            question="\n".join(
                str(record[key]) for key in ("title", "message") if record.get(key)
            )
            or "Pi requests input",
            options=options,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(milliseconds=timeout)
                if type(timeout) is int and timeout > 0
                else None
            ),
        )
        answer = await host.request_input(request)
        payload = {"type": "extension_ui_response", "id": record["id"]}
        if method == "confirm":
            payload["confirmed"] = answer.value
        elif method == "select":
            payload["value"] = record["options"][int(answer.value)]
        else:
            payload["value"] = str(answer.value)
        await rpc.send(payload)

    async def cancel(self, attempt_id: str) -> None:
        if self.rpc and attempt_id == self.active_attempt:
            self.cancelled_attempt = attempt_id
            rpc = self.rpc
            try:
                await rpc.request("clear_queue", timeout=0.2)
                await rpc.request("abort", timeout=0.5)
            except AgentRequestError:
                pass
            finally:
                await rpc.close()  # Confirm the child has stopped before returning.

    async def respond(self, input_request_id, answer) -> None:
        pass  # HostPort.request_input resolves the blocked callback.

    async def close_session(self, session) -> None:
        pass  # No live Pi child is retained between tasks.

    async def shutdown(self) -> None:
        if self.rpc:
            await self.rpc.close()

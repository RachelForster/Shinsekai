"""Deterministic backend for process and host-tool contract checks, without an LLM."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from collections.abc import AsyncIterator

from sdk.agent import (
    AgentBackendCapabilities,
    AgentBackendConfig,
    AgentBackendDescriptor,
    AgentBackendEvent,
    AgentBackendSessionHandle,
    AgentHostPort,
    AgentHostToolCall,
    AgentInputRequest,
    AgentInputAnswer,
    AgentSessionConfig,
    AgentTaskExecution,
    AgentTaskCompletion,
    AgentResult,
    AgentRequestError,
)


class MockAgentBackend:
    async def initialize(self, config: AgentBackendConfig) -> AgentBackendDescriptor:
        return AgentBackendDescriptor(
            backend_id=config.backend_id,
            version="1",
            availability="ready",
            capabilities=AgentBackendCapabilities(
                host_tools=True,
                tool_policy_enforcement=True,
                streaming_text=True,
                interactive_input=True,
                structured_output=True,
            ),
        )

    async def open_session(
        self, config: AgentSessionConfig
    ) -> AgentBackendSessionHandle:
        return AgentBackendSessionHandle({"sessionId": config.session_id})

    async def run(
        self,
        session: AgentBackendSessionHandle,
        task: AgentTaskExecution,
        host: AgentHostPort,
    ) -> AsyncIterator[AgentBackendEvent]:
        # The explicit mock:plan context is a test script, never a system prompt.
        plan = {}
        for context in task.request.context:
            if context.kind == "text" and context.source == "mock:plan":
                plan = json.loads(context.text)
        seq = 0

        def event(kind: str, payload: dict) -> AgentBackendEvent:
            nonlocal seq
            seq += 1
            return AgentBackendEvent(
                attempt_id=task.attempt_id,
                worker_seq=seq,
                timestamp=datetime.now(timezone.utc),
                type=kind,
                payload=payload,
            )

        yield event(
            "message.delta",
            {"messageId": "mock-message", "delta": "Checking the task."},
        )
        await asyncio.sleep(float(plan.get("delayMs", 0)) / 1000)
        if plan.get("crash"):
            os._exit(23)
        data = {"workerPid": os.getpid(), "text": task.request.input.text, "tools": []}
        if plan.get("question"):
            answer = await host.request_input(
                AgentInputRequest(
                    input_request_id="mock-question",
                    kind="question",
                    question=plan["question"],
                )
            )
            data["answer"] = answer.value
        for value in plan.get("tools", []):
            result = await host.invoke_tool(AgentHostToolCall.model_validate(value))
            if not result.ok:
                raise AgentRequestError(result.error)
            data["tools"].append(result.data)
        yield event(
            "message.completed",
            {"messageId": "mock-message", "text": task.request.input.text},
        )
        completion = AgentTaskCompletion(
            status="succeeded",
            result=AgentResult(
                summary="Mock task completed.",
                data=data,
            ),
        )
        yield event("task.completed", completion.to_wire())

    async def cancel(self, attempt_id: str) -> None:
        # Worker owns cancellation of the run coroutine for this backend.
        return None

    async def respond(self, input_request_id: str, answer: AgentInputAnswer) -> None:
        return None

    async def close_session(self, session: AgentBackendSessionHandle) -> None:
        return None

    async def shutdown(self) -> None:
        return None

"""Explicit, typed host tool registration. Skills cannot add permissions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from sdk.agent import (
    AgentHostToolCall,
    AgentHostToolResult,
    AgentTask,
    AgentToolDefinition,
)


@dataclass(frozen=True)
class AgentHostTool:
    definition: AgentToolDefinition
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    execute: Callable[[AgentTask, AgentHostToolCall], AgentHostToolResult]

    @classmethod
    def from_models(
        cls,
        *,
        name: str,
        description: str,
        effect_kind: Literal["read", "write", "execute"],
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        execute: Callable[[AgentTask, AgentHostToolCall], AgentHostToolResult],
    ) -> AgentHostTool:
        return cls(
            AgentToolDefinition(
                name=name,
                description=description,
                effect_kind=effect_kind,
                input_schema=input_model.model_json_schema(),
                output_schema=output_model.model_json_schema(),
            ),
            input_model,
            output_model,
            execute,
        )

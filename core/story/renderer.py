"""Deterministic presentation stub used before Scene LLM integration."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .events import StoryEvent
from .state import StoryState


@dataclass(frozen=True, slots=True)
class StubPresentationEvent:
    kind: str
    speaker_id: str
    text: str
    payload: Mapping[str, Any]


class StubSceneRenderer:
    """Render stable placeholders without model or application dependencies."""

    def render(
        self,
        state: StoryState,
        events: tuple[StoryEvent, ...],
    ) -> tuple[StubPresentationEvent, ...]:
        rendered = []
        for event in events:
            rendered.append(
                StubPresentationEvent(
                    kind="story-event",
                    speaker_id="SYSTEM",
                    text=f"[{event.type.value}]",
                    payload=MappingProxyType(
                        {
                            "eventId": event.id,
                            "revision": event.revision,
                            "currentNodeId": state.current_node_id,
                            **dict(event.payload),
                        }
                    ),
                )
            )
        return tuple(rendered)

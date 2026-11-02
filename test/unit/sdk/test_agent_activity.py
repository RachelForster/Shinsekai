from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sdk.agent import AgentActivityUpdated, AgentBackendEvent, AgentEvent


def test_activity_round_trips_between_worker_and_public_events():
    payload = AgentActivityUpdated(
        activity_id="attempt:read-call",
        kind="tool",
        name="read",
        status="running",
        target="/skills/shinsekai-guide/SKILL.md",
    )
    worker = AgentBackendEvent(
        attempt_id="attempt",
        worker_seq=1,
        timestamp=datetime.now(timezone.utc),
        type="activity.updated",
        payload=payload,
    )
    public = AgentEvent.model_validate(
        {
            "taskId": "task",
            "eventSeq": 1,
            "timestamp": worker.to_wire()["timestamp"],
            "type": worker.type,
            "payload": worker.to_wire()["payload"],
        }
    )
    assert isinstance(public.payload, AgentActivityUpdated)
    assert public.payload == payload
    assert public.to_wire()["payload"]["activityId"] == "attempt:read-call"


@pytest.mark.parametrize(
    "override",
    [
        {"kind": "effects"},
        {"status": "unknown"},
        {"target": "x" * 513},
        {"activityId": " "},
        {"name": True},
    ],
)
def test_invalid_activity_payload_is_rejected(override):
    with pytest.raises(ValidationError):
        AgentActivityUpdated.model_validate(
            {
                "activityId": "activity",
                "kind": "model",
                "name": "thinking",
                "status": "running",
                **override,
            }
        )

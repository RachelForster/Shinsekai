"""Standalone mock task runner: python -m application.agent --task "hello"."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from core.paths import project_root
from application.agent.management import AgentService
from sdk.agent import (
    AgentError,
    AgentOrigin,
    AgentSessionRequest,
    AgentTaskRequest,
    AgentRequestError,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the independent mock Agent task core"
    )
    parser.add_argument("--task", required=True)
    parser.add_argument(
        "--database",
        type=Path,
        default=project_root() / "data" / "agent" / "agent.sqlite",
    )
    parser.add_argument(
        "--resume-queue",
        action="store_true",
        help="Explicitly resume tasks queued before an application restart",
    )
    args = parser.parse_args()
    try:
        with AgentService(args.database) as service:
            if service.queue_paused and not args.resume_queue:
                raise AgentRequestError(
                    AgentError(
                        code="SESSION_BUSY",
                        message="Recovered queue is paused; use --resume-queue to continue",
                    )
                )
            if args.resume_queue:
                service.resume_queue()
            origin = AgentOrigin(kind="user", caller_id="agent-cli")
            client = service.bind(origin)
            session = client.create_session(
                AgentSessionRequest(
                    backend_id="mock", profile_id="basic", model_ref="mock"
                )
            )
            receipt = client.submit_task(
                AgentTaskRequest(
                    request_id=uuid.uuid4().hex,
                    session_id=session.session_id,
                    origin=origin,
                    input={"text": args.task},
                    lifetime="detached",
                )
            )
            print(json.dumps(receipt.to_wire(), ensure_ascii=False), flush=True)
            while True:
                task = client.get_task(receipt.task_id)
                if task.status.is_terminal:
                    print(json.dumps(task.to_wire(), ensure_ascii=False), flush=True)
                    return 0 if task.status == "succeeded" else 1
                time.sleep(0.05)
    except AgentRequestError as exc:
        print(json.dumps({"error": exc.error.to_wire()}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

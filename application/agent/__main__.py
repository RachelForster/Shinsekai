"""Standalone Agent task runner using mock or the official Pi runtime."""

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
    parser = argparse.ArgumentParser(description="Run the independent Agent task core")
    parser.add_argument("--task", required=True)
    parser.add_argument("--backend", choices=("mock", "pi"), default="mock")
    parser.add_argument(
        "--pi-binary", type=Path, help="Use an already installed official Pi binary"
    )
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
        service_options, model_ref = {}, "mock"
        if args.backend == "pi":
            from config.config_manager import ConfigManager
            from application.agent.pi_configuration import prepare_pi_agent
            from core.agent.pi_runtime import PiRuntime

            setup = prepare_pi_agent(
                ConfigManager(),
                runtime=PiRuntime(args.pi_binary) if args.pi_binary else None,
                update_task=lambda **progress: print(
                    json.dumps({"type": "pi.runtime", **progress}, ensure_ascii=False),
                    flush=True,
                ),
            )
            service_options = {
                "backend": setup.backend,
                "worker_environment": setup.worker_environment,
            }
            model_ref = setup.model_ref
        with AgentService(args.database, **service_options) as service:
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
                    backend_id=args.backend, profile_id="basic", model_ref=model_ref
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

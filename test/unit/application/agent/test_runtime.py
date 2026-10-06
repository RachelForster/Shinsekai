from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from application.agent.management import AgentService
from application.agent.pi_configuration import resolve_pi_model
from application.agent.runtime import AgentRuntime, UI_ORIGIN
from application.runtime.services import ApplicationServices
from sdk.agent import (
    AgentBackendConfig,
    AgentRequestError,
    AgentSessionRequest,
    AgentTaskRequest,
)


class ModelConfig:
    model = "test-model"
    key = "private-test-key"
    config = SimpleNamespace(api_config=SimpleNamespace(max_context_tokens=8192))

    def get_llm_api_config(self):
        return "ChatGPT", self.model, "https://example.com/v1", self.key

    def update_llm_info(self, provider):
        return "https://example.com/v1", self.model, self.key


def mock_setup(config, **kwargs):
    return SimpleNamespace(
        backend=AgentBackendConfig(backend_id="mock", backend_version="1"),
        model_ref=resolve_pi_model(config).reference,
        worker_environment=lambda: {},
    )


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("Agent runtime condition timed out")


def test_preparation_is_nonblocking_and_close_prevents_late_dispatch(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def prepare(config, **kwargs):
        entered.set()
        kwargs["update_task"](phase="download", progress=0.4)
        release.wait(5)
        assert kwargs["is_interrupted"]()
        return mock_setup(config)

    runtime = AgentRuntime(ModelConfig(), tmp_path, prepare=prepare)
    runtime.start()
    assert entered.wait(3)
    assert runtime.snapshot()["phase"] == "download"
    with runtime.access() as client:
        assert not client.list_sessions().sessions
    with pytest.raises(AgentRequestError):
        runtime.create_session()
    runtime.close()
    release.set()
    runtime._thread.join(3)
    assert runtime.snapshot()["status"] == "stopped"
    assert runtime._service._thread is None
    assert runtime._service._closed


def test_preparation_failure_keeps_history_and_retry_can_start(tmp_path):
    calls = []

    def prepare(config, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("private-test-key must not reach the UI")
        return mock_setup(config)

    runtime = AgentRuntime(ModelConfig(), tmp_path, prepare=prepare)
    try:
        runtime.start()
        wait_for(lambda: runtime.snapshot()["status"] == "error")
        assert "private-test-key" not in json.dumps(runtime.snapshot())
        with runtime.access() as client:
            assert not client.list_tasks().tasks
        runtime._thread.join(2)
        runtime.start()
        wait_for(lambda: runtime.snapshot()["status"] == "ready")
        assert runtime.create_session().owner == UI_ORIGIN
    finally:
        runtime.close()


def seed_queue(root, config):
    service = AgentService(
        root / "agent.sqlite",
        backend=AgentBackendConfig(backend_id="mock", backend_version="1"),
    )
    client = service.bind(UI_ORIGIN, administrator=True)
    session = client.create_session(
        AgentSessionRequest(
            backend_id="mock",
            profile_id="basic",
            model_ref=resolve_pi_model(config).reference,
        )
    )
    receipt = client.submit_task(
        AgentTaskRequest(
            request_id="queued",
            session_id=session.session_id,
            origin=UI_ORIGIN,
            input={"text": "queued question"},
            lifetime="detached",
        )
    )
    service.close()
    return session, receipt


def test_recovered_queue_waits_for_explicit_resume(tmp_path):
    config = ModelConfig()
    session, receipt = seed_queue(tmp_path, config)
    runtime = AgentRuntime(config, tmp_path, prepare=mock_setup)
    try:
        runtime.start()
        wait_for(lambda: runtime.snapshot()["status"] == "ready")
        assert runtime.snapshot()["queuePaused"]
        with runtime.access() as client:
            assert client.get_task(receipt.task_id).status == "queued"
            assert client.list_sessions().sessions[0].session_id == session.session_id
        assert runtime._service._supervisor.process is None
        runtime.resume_queue()
        with runtime.access() as client:
            wait_for(lambda: client.get_task(receipt.task_id).status.is_terminal)
    finally:
        runtime.close()


def test_model_change_cannot_transfer_queued_work(tmp_path):
    config = ModelConfig()
    _, receipt = seed_queue(tmp_path, config)
    runtime = AgentRuntime(config, tmp_path, prepare=mock_setup)
    try:
        runtime.start()
        wait_for(lambda: runtime.snapshot()["status"] == "ready")
        runtime._thread.join(2)
        config.model = "new-model"
        assert runtime.snapshot()["configurationChanged"]
        with pytest.raises(AgentRequestError) as error:
            runtime.start()
        assert error.value.error.code == "SESSION_BUSY"
        with runtime.access() as client:
            client.cancel_task(receipt.task_id)
        runtime.start()
        wait_for(
            lambda: runtime.snapshot()["status"] == "ready"
            and not runtime.snapshot()["configurationChanged"]
        )
        assert runtime.create_session().model_ref == resolve_pi_model(config).reference
    finally:
        runtime.close()


def test_shutdown_cancels_active_worker_and_releases_database(tmp_path):
    runtime = AgentRuntime(ModelConfig(), tmp_path, prepare=mock_setup)
    try:
        runtime.start()
        wait_for(lambda: runtime.snapshot()["status"] == "ready")
        session = runtime.create_session()
        with runtime.access() as client:
            receipt = client.submit_task(
                AgentTaskRequest(
                    request_id="active",
                    session_id=session.session_id,
                    origin=UI_ORIGIN,
                    input={"text": "question"},
                    context=(
                        {
                            "kind": "text",
                            "source": "mock:plan",
                            "text": json.dumps({"delayMs": 30000}),
                        },
                    ),
                    lifetime="detached",
                )
            )
            wait_for(
                lambda: any(
                    event.type == "message.delta"
                    for event in client.read_events(receipt.task_id).events
                )
            )
        process = runtime._service._supervisor.process
        assert process is not None
        errors = []

        def stop():
            try:
                runtime.close()
            except Exception as exc:
                errors.append(exc)

        stops = [threading.Thread(target=stop) for _ in range(2)]
        for thread in stops:
            thread.start()
        for thread in stops:
            thread.join(8)
        assert not errors
        assert all(not thread.is_alive() for thread in stops)
        assert process.poll() is not None
        assert runtime._service._closed
        with AgentService(tmp_path / "agent.sqlite") as reopened:
            task = reopened.bind(UI_ORIGIN, administrator=True).get_task(
                receipt.task_id
            )
            assert task.status.is_terminal
    finally:
        runtime.close()


def test_application_services_has_one_agent_owner(monkeypatch, tmp_path):
    calls = []

    class Runtime:
        def __init__(self, config, root):
            calls.append((config, root))

        def start(self):
            calls.append("start")

        def close(self):
            calls.append("close")

    monkeypatch.setattr("application.agent.runtime.AgentRuntime", Runtime)
    services = ApplicationServices()
    services.start_agent("config", tmp_path)
    services.start_agent("config", tmp_path)
    services.close()
    assert calls == [("config", tmp_path), "start", "start", "close"]


def test_backend_preparation_is_forbidden_after_dispatch_starts(tmp_path):
    with AgentService(tmp_path / "agent.sqlite") as service:
        with pytest.raises(AgentRequestError) as error:
            service.configure_backend(
                AgentBackendConfig(backend_id="pi", backend_version="1")
            )
        assert error.value.error.code == "SESSION_BUSY"

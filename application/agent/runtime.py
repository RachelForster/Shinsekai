"""Application lifecycle for the user-facing Agent, owned by the bridge."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from application.agent.management import AgentProfile, AgentService
from application.agent.pi_configuration import prepare_pi_agent, resolve_pi_model
from core.agent.ipc import fault
from sdk.agent import (
    AgentBackendConfig,
    AgentClient,
    AgentError,
    AgentLimits,
    AgentOrigin,
    AgentRequestError,
    AgentSessionRequest,
)


UI_ORIGIN = AgentOrigin(kind="user", caller_id="shinsekai-assistant")
ASSISTANT_PROFILE = AgentProfile(
    limits=AgentLimits(wall_time_ms=300000, max_tool_calls=20),
)


class AgentRuntime:
    """Keep history readable while Pi installation/configuration is unavailable.

    Preparation runs in a cancellable background thread. Only this owner may
    switch configuration, and recovered queued tasks require explicit resume.
    Closing a panel has no effect on this application-owned lifecycle.
    """

    def __init__(
        self,
        config_manager,
        root: str | Path,
        *,
        prepare: Callable = prepare_pi_agent,
        service_factory: Callable = AgentService,
    ) -> None:
        self.config_manager = config_manager
        self.root = Path(root).resolve()
        self._prepare = prepare
        self._service_factory = service_factory
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._service: AgentService | None = None
        self._setup = None
        self._status = "idle"
        self._phase = ""
        self._progress = 0.0
        self._error: AgentError | None = None

    def start(self) -> None:
        with self._lock:
            self._ensure_open()
            if self._thread is not None and self._thread.is_alive():
                return
            if self._status == "ready":
                current = resolve_pi_model(self.config_manager)
                if current.reference == self._setup.model_ref:
                    return
                with self.access() as client:
                    if client.list_tasks(
                        statuses=("queued", "running", "waiting_input", "cancelling"),
                        limit=1000,
                    ).tasks:
                        raise fault(
                            "SESSION_BUSY",
                            "Finish or cancel pending Agent tasks before changing the model",
                        )
            self._status, self._phase, self._progress = "preparing", "configure", 0.0
            self._error = None
            self._thread = threading.Thread(
                target=self._initialize, name="agent-runtime-prepare", daemon=True
            )
            self._thread.start()

    def _initialize(self) -> None:
        try:
            with self._lock:
                if self._stop.is_set():
                    return
                if self._service is None:
                    self._service = self._service_factory(
                        self.root / "agent.sqlite",
                        backend=AgentBackendConfig(
                            backend_id="pi", backend_version="1"
                        ),
                        profiles=(ASSISTANT_PROFILE,),
                    )
            setup = self._prepare(
                self.config_manager,
                root=self.root,
                update_task=self._update_progress,
                is_interrupted=self._stop.is_set,
            )
            with self._lock:
                if self._stop.is_set():
                    return
                # Configuration changes are allowed only after pending work has
                # settled. Never transfer queued work to a different model.
                if self._setup is not None:
                    self._service.close()
                    self._service = self._service_factory(
                        self.root / "agent.sqlite",
                        backend=setup.backend,
                        profiles=(ASSISTANT_PROFILE,),
                        worker_environment=setup.worker_environment,
                    )
                else:
                    self._service.configure_backend(
                        setup.backend, worker_environment=setup.worker_environment
                    )
                self._setup = setup
                self._service.start()
                self._status, self._phase, self._progress = "ready", "ready", 1.0
        except Exception as exc:
            with self._lock:
                if not self._stop.is_set():
                    self._status = "error"
                    self._error = (
                        exc.error
                        if isinstance(exc, AgentRequestError)
                        else AgentError(
                            code="BACKEND_UNAVAILABLE",
                            message="Agent preparation failed; check the model configuration and network, then retry",
                            retryable=True,
                        )
                    )

    def _update_progress(self, **values) -> None:
        with self._lock:
            if not self._stop.is_set():
                self._phase = str(values.get("phase", self._phase))
                self._progress = max(
                    0.0, min(1.0, float(values.get("progress", self._progress)))
                )

    def _ensure_open(self) -> None:
        if self._stop.is_set():
            raise fault("BACKEND_UNAVAILABLE", "Agent runtime is shutting down")

    @contextmanager
    def access(self, *, ready: bool = False) -> Iterator[AgentClient]:
        with self._lock:
            self._ensure_open()
            if self._service is None:
                raise AgentRequestError(
                    AgentError(
                        code="BACKEND_UNAVAILABLE",
                        message="Agent history is initializing",
                        retryable=True,
                    )
                )
            if ready and self._status != "ready":
                raise AgentRequestError(
                    self._error
                    or AgentError(
                        code="BACKEND_UNAVAILABLE",
                        message="Agent runtime is preparing",
                        retryable=True,
                    )
                )
            yield self._service.bind(UI_ORIGIN, administrator=True)

    def snapshot(self) -> dict:
        with self._lock:
            changed = False
            if self._setup is not None and not self._stop.is_set():
                try:
                    changed = (
                        resolve_pi_model(self.config_manager).reference
                        != self._setup.model_ref
                    )
                except AgentRequestError:
                    changed = True
            return {
                "status": self._status,
                "phase": self._phase,
                "progress": self._progress,
                "backendId": "pi",
                "modelRef": self._setup.model_ref if self._setup else None,
                "configurationChanged": changed,
                "queuePaused": bool(self._service and self._service.queue_paused),
                "error": self._error.to_wire() if self._error else None,
            }

    def create_session(self):
        with self.access(ready=True) as client:
            if self.snapshot()["configurationChanged"]:
                raise fault(
                    "SESSION_BACKEND_MISMATCH",
                    "Apply the current model configuration before creating a session",
                )
            return client.create_session(
                AgentSessionRequest(
                    backend_id=self._setup.backend.backend_id,
                    profile_id="basic",
                    model_ref=self._setup.model_ref,
                )
            )

    def resume_queue(self) -> None:
        with self.access(ready=True):
            if self.snapshot()["configurationChanged"]:
                raise fault(
                    "SESSION_BACKEND_MISMATCH",
                    "Apply the current model configuration before resuming the queue",
                )
            self._service.resume_queue()

    def close(self, *, timeout: float = 5) -> None:
        # Do not join the download while holding the lock its progress callback
        # needs. The stop flag prevents any late installation from starting work.
        with self._lock:
            self._stop.set()
            self._status = "stopped"
            service = self._service
        if service is not None:
            service.close(timeout=timeout)

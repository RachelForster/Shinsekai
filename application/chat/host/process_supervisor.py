"""Own one child and its log, with injectable process primitives and observers."""

from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from datetime import datetime
import logging
from pathlib import Path
import signal
import subprocess
import threading
import uuid
from collections.abc import Callable
from typing import TextIO

from application.chat.host.ports import (
    ChildProcess,
    LaunchPlan,
    LaunchRejected,
    LaunchSystem,
    LifecyclePublisher,
    MemoryProcessResources,
    ProcessResources,
    TerminationSystem,
)
from sdk.chat_lifecycle import ChatProcessContext, ChatProcessEvent

logger = logging.getLogger(__name__)


def tail_text(path: Path, max_chars: int = 2400) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if len(text) <= max_chars else text[-max_chars:]


class ProcessTermination:
    """Platform signalling and the bounded graceful/terminate/kill policy."""

    def __init__(self, system: TerminationSystem) -> None:
        self.system = system

    def hidden_kwargs(self) -> dict:
        if self.system.platform() != "nt":
            return {"start_new_session": True}
        return {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        }

    def signal_tree(self, process: ChildProcess, signum: int) -> None:
        if self.system.platform() != "nt":
            try:
                self.system.group_signal(process.pid, signum)
                return
            except ProcessLookupError:
                if process.poll() is not None:
                    return
            except OSError:
                pass
        try:
            process.send_signal(signum)
        except (OSError, ValueError):
            pass

    def wait_exit(self, process: ChildProcess, timeout: float) -> bool:
        try:
            process.wait(timeout=max(timeout, 0.0))
            return True
        except subprocess.TimeoutExpired:
            return False

    def stop(self, process: ChildProcess, *, wait_timeout: float) -> None:
        if process.poll() is not None:
            return
        deadline = self.system.monotonic() + max(wait_timeout, 0.15)
        steps = [
            (signal.SIGINT, max(0.45, wait_timeout - 0.7)),
            (signal.SIGTERM, 0.35),
            ("kill", 0.35),
        ]
        for action, step_timeout in steps:
            if process.poll() is not None:
                return
            if action == "kill":
                if self.system.platform() != "nt":
                    self.signal_tree(process, signal.SIGKILL)
                else:
                    try:
                        process.kill()
                    except OSError:
                        pass
            elif self.system.platform() == "nt" and action == signal.SIGTERM:
                try:
                    process.terminate()
                except OSError:
                    pass
            else:
                self.signal_tree(process, int(action))
            remaining = max(0.05, min(step_timeout, deadline - self.system.monotonic()))
            if self.wait_exit(process, remaining):
                return


class ChatProcessSupervisor:
    """Serialize transitions while keeping callbacks outside the resource mutex."""

    def __init__(
        self,
        *,
        system: LaunchSystem,
        log_path: Callable[[], Path],
        hidden_kwargs: Callable[[], dict],
        stop_child: Callable[..., None],
        wait_exit: Callable[[ChildProcess, float], bool],
        monotonic: Callable[[], float],
        failed_launch: Callable[[int, Path], str],
        resources: ProcessResources | None = None,
        publish: LifecyclePublisher | None = None,
        spawn: Callable[..., tuple[ChildProcess, Path]] | None = None,
        handle_event: LifecyclePublisher | None = None,
        watch_exits: bool = False,
        watch_interval: float = 0.1,
    ) -> None:
        self.system, self.log_path, self.hidden_kwargs = system, log_path, hidden_kwargs
        self.stop_child, self.wait_exit, self.monotonic = (
            stop_child,
            wait_exit,
            monotonic,
        )
        self.failed_launch = failed_launch
        self.resources = (
            resources if resources is not None else MemoryProcessResources()
        )
        self.publish = publish or (lambda _context: None)
        self.handle_event = handle_event or (lambda _context: None)
        self.watch_exits, self.watch_interval = watch_exits, watch_interval
        self.spawn_child = spawn or self.spawn
        self._gate = threading.RLock()
        self._transitioning = False
        self._terminal_events: list[ChatProcessContext] | None = None
        self._delivery = threading.local()
        self._owner: tuple[ChildProcess, ChatProcessContext] | None = None

    @contextmanager
    def _transition(self):
        terminal_events: list[ChatProcessContext] = []
        try:
            with self._gate:
                if self._transitioning:
                    yield False
                    return
                self._transitioning = True
                self._terminal_events = terminal_events
                try:
                    yield True
                finally:
                    self._terminal_events = None
                    self._transitioning = False
        finally:
            # Session cleanup may acquire a bridge lifecycle lock. Deliver only
            # after releasing the process gate to avoid opposite lock ordering.
            for context in terminal_events:
                self._deliver(context)

    def _notify(self, context: ChatProcessContext) -> None:
        if (
            context.event in {ChatProcessEvent.STOPPED, ChatProcessEvent.FAILED}
            and self._terminal_events is not None
        ):
            self._terminal_events.append(context)
            return
        self._deliver(context)

    def _deliver(self, context: ChatProcessContext) -> None:
        # Application handlers report failures to the owner. The legacy publish
        # callback remains an observation boundary for optional extensions.
        previous = getattr(self._delivery, "active", False)
        self._delivery.active = True
        try:
            try:
                self.handle_event(context)
            finally:
                self._observe(context)
        finally:
            self._delivery.active = previous

    def _observe(self, context: ChatProcessContext) -> None:
        try:
            self.publish(context)
        except Exception:
            logger.warning(
                "Chat process observer failed in %s", context.event.value, exc_info=True
            )

    def running(self) -> bool:
        with self.resources.lock:
            child = self.resources.process
            running = child is not None and child.poll() is None
            owner = self._owner
        if child is not None and not running and owner is not None:
            self.observe_exit(child, owner[1])
        return running

    def observe_exit(self, child: ChildProcess, context: ChatProcessContext) -> None:
        with self._transition() as acquired:
            if not acquired:
                return
            with self.resources.lock:
                if (
                    self.resources.process is not child
                    or self._owner is None
                    or self._owner[0] is not child
                    or self._owner[1].launch_id != context.launch_id
                ):
                    return
                exit_code = child.poll()
                if exit_code is None:
                    return
                handle, self.resources.log = self.resources.log, None
                self.resources.process = None
                self._owner = None
            self._close(handle)
            self._notify(
                replace(
                    context,
                    event=(
                        ChatProcessEvent.STOPPED
                        if exit_code == 0
                        else ChatProcessEvent.FAILED
                    ),
                    exit_code=exit_code,
                    reason="exited" if exit_code == 0 else "unexpected_exit",
                )
            )

    def _watch_exit(self, child: ChildProcess, context: ChatProcessContext) -> None:
        delay = threading.Event()
        while not delay.wait(max(0.01, self.watch_interval)):
            with self.resources.lock:
                if self.resources.process is not child:
                    return
            try:
                if child.poll() is not None:
                    self.observe_exit(child, context)
                    return
            except Exception:
                logger.exception("Chat exit monitoring or application cleanup failed")
                return

    @staticmethod
    def _close(handle: TextIO | None) -> None:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def close_log(self) -> None:
        with self.resources.lock:
            handle, self.resources.log = self.resources.log, None
        self._close(handle)

    def spawn(
        self, command: list[str], *, cwd: Path, env: dict[str, str]
    ) -> tuple[ChildProcess, Path]:
        self.close_log()
        path = self.log_path()
        handle = path.open("a", encoding="utf-8", buffering=1)
        with self.resources.lock:
            self.resources.log = handle
        try:
            handle.write(
                "\n"
                + "=" * 60
                + f"\n{datetime.now().isoformat(sep=' ', timespec='seconds')}  main.py launch\n"
                + f"cwd: {cwd}\n"
                + f"cmd: {' '.join(command)}\n"
            )
            child = self.system.popen(
                command,
                cwd=str(cwd),
                env={**env, "PYTHONUNBUFFERED": "1"},
                stdout=handle,
                stderr=subprocess.STDOUT,
                **self.hidden_kwargs(),
            )
        except BaseException:
            with self.resources.lock:
                if self.resources.log is handle:
                    self.resources.log = None
            self._close(handle)
            raise
        return child, path

    def launch(
        self,
        prepare: Callable[[], LaunchPlan | LaunchRejected],
        *,
        session_id: str = "",
        launch_id: str = "",
    ) -> str:
        if getattr(self._delivery, "active", False):
            return "聊天进程正在启动或关闭中。"
        self.running()
        with self._transition() as acquired:
            if not acquired:
                return "聊天进程正在启动或关闭中。"
            with self.resources.lock:
                child = self.resources.process
                if child is not None and child.poll() is None:
                    return f"进程已经在运行中！PID: {child.pid}"
                self.resources.process = None
                self._owner = None
            self.close_log()
            context = ChatProcessContext(
                ChatProcessEvent.STARTING,
                session_id=session_id,
                launch_id=launch_id or uuid.uuid4().hex,
            )
            child = None
            try:
                self._notify(context)
                plan = prepare()
                if isinstance(plan, LaunchRejected):
                    self._notify(
                        replace(
                            context, event=ChatProcessEvent.FAILED, reason=plan.message
                        )
                    )
                    return plan.message
                child, path = self.spawn_child(
                    plan.command, cwd=plan.cwd, env=plan.environment
                )
                with self.resources.lock:
                    self.resources.process = child
                context = replace(context, pid=child.pid)
                self._owner = (child, context)
                try:
                    exit_code = child.wait(timeout=1.2)
                except subprocess.TimeoutExpired:
                    self._notify(replace(context, event=ChatProcessEvent.STARTED))
                    if self.watch_exits:
                        threading.Thread(
                            target=self._watch_exit,
                            args=(child, context),
                            name=f"chat-exit-{context.launch_id[:8]}",
                            daemon=True,
                        ).start()
                    return f"聊天进程已启动！PID: {child.pid}"
                self.close_log()
                with self.resources.lock:
                    if self.resources.process is child:
                        self.resources.process = None
                self._owner = None
                message = self.failed_launch(exit_code, path)
                self._notify(
                    replace(
                        context,
                        event=ChatProcessEvent.FAILED,
                        exit_code=exit_code,
                        reason=message,
                    )
                )
                return message
            except BaseException as error:
                if child is not None and child.poll() is None:
                    try:
                        self.stop_child(child, wait_timeout=1.2)
                    except Exception:
                        logger.warning(
                            "Could not stop failed chat launch", exc_info=True
                        )
                if child is not None and child.poll() is not None:
                    with self.resources.lock:
                        if self.resources.process is child:
                            self.resources.process = None
                    self._owner = None
                self.close_log()
                self._notify(
                    replace(
                        context,
                        event=ChatProcessEvent.FAILED,
                        error=error,
                        reason=str(error),
                    )
                )
                raise

    def shutdown(
        self, *, wait_timeout: float = 1.2, wait_before_signal: float = 0.0
    ) -> None:
        if getattr(self._delivery, "active", False):
            return
        with self._transition() as acquired:
            if not acquired:
                return
            with self.resources.lock:
                child, handle = self.resources.process, self.resources.log
            if child is None:
                self.close_log()
                return
            already_exited = child.poll() is not None
            context = (
                self._owner[1]
                if self._owner is not None and self._owner[0] is child
                else ChatProcessContext(ChatProcessEvent.STOPPING, pid=child.pid)
            )
            error: BaseException | None = None
            try:
                self._notify(replace(context, event=ChatProcessEvent.STOPPING))
                if child.poll() is None:
                    started = self.monotonic()
                    exited = wait_before_signal > 0 and self.wait_exit(
                        child, min(wait_before_signal, wait_timeout)
                    )
                    if not exited:
                        remaining = max(
                            0.15, wait_timeout - (self.monotonic() - started)
                        )
                        self.stop_child(child, wait_timeout=remaining)
            except BaseException as failure:
                error = failure
                raise
            finally:
                with self.resources.lock:
                    if self.resources.process is child:
                        self.resources.process = None
                    if self.resources.log is handle:
                        self.resources.log = None
                self._close(handle)
                exit_code = child.poll()
                event = (
                    ChatProcessEvent.STOPPED
                    if error is None
                    and exit_code is not None
                    and (not already_exited or exit_code == 0)
                    else ChatProcessEvent.FAILED
                )
                self._notify(
                    replace(
                        context,
                        event=event,
                        exit_code=exit_code,
                        error=error,
                        reason=(
                            "unexpected_exit"
                            if already_exited and exit_code != 0
                            else "shutdown"
                        ),
                    )
                )
                if self._owner is not None and self._owner[0] is child:
                    self._owner = None

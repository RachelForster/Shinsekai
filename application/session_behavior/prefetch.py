"""Isolated speculative prefetch coordinator for multi-beat narrative continuation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Any
import uuid

from ai.llm.speculative_dialog import (
    SpeculativeDialogResult,
    run_speculative_dialog_generation,
)
from ai.llm.template.integrations.localization import LocaleInput


@dataclass
class PrefetchHandle:
    """In-flight or completed speculative prefetch ticket."""

    request_id: str
    cache_key: str
    branch_id: str
    state_version: int
    cancel_event: threading.Event
    future: Future[SpeculativeDialogResult]

    def cancel(self) -> None:
        self.cancel_event.set()
        self.future.cancel()

    def is_done(self) -> bool:
        return self.future.done()

    def result(self, timeout: float | None = None) -> SpeculativeDialogResult | None:
        if self.cancel_event.is_set() and not self.future.done():
            return SpeculativeDialogResult(cancelled=True)
        try:
            return self.future.result(timeout=timeout)
        except Exception:
            if self.cancel_event.is_set():
                return SpeculativeDialogResult(cancelled=True)
            raise


class SpeculativePrefetchCoordinator:
    """Manage one isolated background speculative LLM worker (max_inflight=1)."""

    def __init__(
        self,
        *,
        create_prefetch_adapter: Callable[[], Any],
        max_repair_retries: int = 2,
        locale_provider: Callable[[], LocaleInput] | None = None,
    ) -> None:
        self._create_prefetch_adapter = create_prefetch_adapter
        self._max_repair_retries = max(1, int(max_repair_retries))
        self._locale_provider = locale_provider
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="behavior-prefetch",
        )
        self._active_handle: PrefetchHandle | None = None
        self._active_adapter: Any | None = None
        self._completed: dict[tuple[str, str, int], SpeculativeDialogResult] = {}
        self._closed = False

    def _cancel_active_locked(self) -> None:
        if self._active_handle is not None:
            self._active_handle.cancel()
        if self._active_adapter is not None:
            cancel_fn = getattr(self._active_adapter, "cancel", None)
            if callable(cancel_fn):
                try:
                    cancel_fn()
                except Exception:
                    pass
        self._active_handle = None

    def schedule(
        self,
        *,
        cache_key: str,
        branch_id: str,
        state_version: int,
        messages: Sequence[Mapping[str, Any]],
        system_prompt: str | None = None,
        generation_kwargs: Mapping[str, Any] | None = None,
        media_selection_mode: str = "indexed",
        speaker_requires_media: Callable[[str], bool] | None = None,
        bound_speakers: Sequence[str] = (),
    ) -> PrefetchHandle:
        """Schedule at most one background prefetch; supersedes any older ticket."""
        key = (str(branch_id or "main"), str(cache_key), int(state_version))
        with self._lock:
            if self._closed:
                raise RuntimeError("SpeculativePrefetchCoordinator is shut down")
            if (
                self._active_handle is not None
                and not self._active_handle.cancel_event.is_set()
                and self._active_handle.cache_key == key[1]
                and self._active_handle.branch_id == key[0]
                and self._active_handle.state_version == key[2]
            ):
                return self._active_handle

            self._cancel_active_locked()
            self._completed.clear()
            cancel_event = threading.Event()
            request_id = uuid.uuid4().hex
            locale = self._locale_provider() if callable(self._locale_provider) else None

            def _run() -> SpeculativeDialogResult:
                if cancel_event.is_set():
                    return SpeculativeDialogResult(cancelled=True)
                adapter = self._create_prefetch_adapter()
                with self._lock:
                    if cancel_event.is_set():
                        cancel_fn = getattr(adapter, "cancel", None)
                        if callable(cancel_fn):
                            try:
                                cancel_fn()
                            except Exception:
                                pass
                        return SpeculativeDialogResult(cancelled=True)
                    self._active_adapter = adapter
                try:
                    res = run_speculative_dialog_generation(
                        adapter=adapter,
                        messages=messages,
                        system_prompt=system_prompt,
                        generation_kwargs=generation_kwargs,
                        cancel_event=cancel_event,
                        media_selection_mode=media_selection_mode,
                        speaker_requires_media=speaker_requires_media,
                        bound_speakers=bound_speakers,
                        max_repair_retries=self._max_repair_retries,
                        locale=locale,
                    )
                finally:
                    with self._lock:
                        if self._active_adapter is adapter:
                            self._active_adapter = None
                if not cancel_event.is_set() and not res.cancelled and not res.error:
                    with self._lock:
                        self._completed[key] = res
                return res

            future = self._executor.submit(_run)
            handle = PrefetchHandle(
                request_id=request_id,
                cache_key=key[1],
                branch_id=key[0],
                state_version=key[2],
                cancel_event=cancel_event,
                future=future,
            )
            self._active_handle = handle
            return handle

    def consume_if_valid(
        self,
        cache_key: str,
        *,
        branch_id: str,
        state_version: int,
        wait_timeout: float = 0.0,
    ) -> SpeculativeDialogResult | None:
        """Return and pop a completed valid prefetch matching branch, version, and key."""
        key = (str(branch_id or "main"), str(cache_key), int(state_version))
        handle: PrefetchHandle | None
        with self._lock:
            cached = self._completed.pop(key, None)
            if cached is not None:
                if (
                    self._active_handle is not None
                    and (
                        self._active_handle.branch_id,
                        self._active_handle.cache_key,
                        self._active_handle.state_version,
                    )
                    == key
                ):
                    self._active_handle = None
                return None if cached.cancelled or cached.error else cached
            handle = self._active_handle

        if (
            handle is not None
            and not handle.cancel_event.is_set()
            and (handle.branch_id, handle.cache_key, handle.state_version) == key
        ):
            if wait_timeout > 0.0 or handle.future.done():
                try:
                    res = handle.future.result(timeout=max(0.0, float(wait_timeout)))
                except Exception:
                    return None
                with self._lock:
                    self._completed.pop(key, None)
                    if self._active_handle is handle:
                        self._active_handle = None
                if not res.cancelled and not res.error:
                    return res
        return None

    def invalidate_all(self) -> None:
        """Cancel any in-flight prefetch and discard all cached results."""
        with self._lock:
            self._cancel_active_locked()
            self._completed.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_active_locked()
            self._completed.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "PrefetchHandle",
    "SpeculativePrefetchCoordinator",
]

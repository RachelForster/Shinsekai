from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, TypeVar

from i18n import current_language, normalize_lang, tr_in_bundle

E = TypeVar("E", bound=Exception)

_ACTIVE_BRIDGE_STATE: ContextVar[Any] = ContextVar("_ACTIVE_BRIDGE_STATE", default=None)


@contextmanager
def bind_bridge_state(state: Any) -> Iterator[None]:
    """Bind BridgeState for nested helper functions that preserve legacy signatures."""
    if state is None:
        yield
        return
    token = _ACTIVE_BRIDGE_STATE.set(state)
    try:
        yield
    finally:
        _ACTIVE_BRIDGE_STATE.reset(token)


def bridge_locale(state: Any = None) -> str:
    """Resolve the active UI language from BridgeState or process i18n context."""
    resolved_state = state if state is not None else _ACTIVE_BRIDGE_STATE.get()
    if resolved_state is not None:
        stores = getattr(resolved_state, "stores", None)
        if stores is not None:
            try:
                raw = str(
                    getattr(stores.system_settings.get(), "ui_language", "") or ""
                ).strip()
                if raw:
                    return normalize_lang(raw)
            except Exception:
                pass
        cfg_mgr = getattr(resolved_state, "config_manager", None)
        cfg = getattr(cfg_mgr, "config", None)
        sys_cfg = getattr(cfg, "system_config", None)
        raw = str(getattr(sys_cfg, "ui_language", "") or "").strip()
        if raw:
            return normalize_lang(raw)
    return current_language()


def bridge_tr(state: Any, key: str, **params: Any) -> str:
    """Translate a bridge UI/task/error message under the active UI language."""
    full_key = key if key.startswith("bridge.") else f"bridge.{key}"
    return tr_in_bundle(full_key, bridge_locale(state), **params)


def bridge_error(
    exc_cls: type[E],
    state: Any,
    code: str,
    *,
    key: str | None = None,
    **params: Any,
) -> E:
    """Instantiate ``exc_cls`` with a localized message and structured errorCode/errorParams."""
    msg_key = key or f"err.{code}"
    message = bridge_tr(state, msg_key, **params)
    exc = exc_cls(message)
    setattr(exc, "error_code", code)
    if params:
        setattr(exc, "error_params", dict(params))
    return exc

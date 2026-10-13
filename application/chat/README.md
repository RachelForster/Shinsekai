# Chat runtime responsibilities

The public compatibility entry point is `runtime_process.py`. Its previous
implementation combined process ownership, launch preparation, transport
snapshots, history download capabilities, story persistence and command routing.
Characterization tests exercise the original entry points before extraction.

## Lifecycle assessment

`init_chat` already reports provider/plugin initialization in the child process.
The existing shutdown registry supplies process-local cleanup actions. Neither
notifies bridge extensions when the chat child is launched, stopped or fails.
Tracing, diagnostics and extension-resource cleanup need these shared boundaries
across normal API shutdown and bridge watchdog/signal shutdown.

The SDK therefore defines `ChatProcessEvent` and immutable `ChatProcessContext`.
Register observers through `PluginCapabilityRegistry.register_chat_process_hook`:

- `STARTING`: a new launch attempt, before configuration and template preparation.
- `STARTED`: the child survived the initial process-exit check; this is separate
  from provider readiness reported by `init_chat`.
- `STOPPING`: shutdown has selected the child it owns.
- `STOPPED`: the child exited and its owned log has been released.
- `FAILED`: launch/preparation or shutdown failed, including an early exit.

The context contains session ID, PID, exit code, reason and the original error.
It exposes no host state, environment or launch configuration. These are
observation hooks: failures are logged and later hooks continue; they do not veto
launch or prevent process cleanup. Critical initialization work continues to use
`register_init_chat_hook(..., critical=True)`.

Example:

```python
from sdk import ChatProcessEvent

def register(registry):
    registry.register_chat_process_hook(
        ChatProcessEvent.STOPPED,
        lambda context: release_session_resources(context.session_id),
        label="release_session_resources",
    )
```

Lifecycle publishing belongs to the process owner so watchdog shutdown can notify
observers without an HTTP request or mutable bridge state. Application services
consume narrow ports; the composition root connects the existing SDK dispatcher.

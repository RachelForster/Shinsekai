# Chat runtime responsibilities

The public compatibility entry point is `runtime_process.py`. Its previous
implementation combined process ownership, launch preparation, transport
snapshots, history download capabilities, story persistence and command routing.
Characterization tests exercise the original entry points before extraction.

| Module | Responsibility | Dependencies |
| --- | --- | --- |
| `runtime_process.py` | Compatibility entry points and default service wiring | Existing bridge state and host adapters |
| `process_supervisor.py` | Child/log ownership, serialized lifecycle, bounded termination | Process primitives, resource slots, observer callback |
| `launch_preparation.py` | Templates, configuration and trusted launch plan | Root/entrypoint callbacks and existing config helpers |
| `runtime_projection.py` | Snapshot composition, identity and media defaults | History callback, runtime status and story/mobile projections |
| `runtime_history.py` | History projection and expiring download capabilities | Path/read/name callbacks, clock and token factory |
| `runtime_story.py` | Story history persistence and branch coordination | History and story ports |
| `runtime_commands.py` | Registered command handlers and transport delivery policy | Ports and callbacks required by each handler group |
| `runtime_ports.py` | Structural contracts and callable adapters | Standard library and SDK lifecycle types |

Handlers extend `ChatCommandRouter` through `register`; the router and shared
delivery policy do not need new command branches. Local handlers must explicitly
opt out of child transport. History, story, snapshot and process tests can supply
small substitutes without constructing the plugin host or frontend transport.

The process-global slots remain at the compatibility boundary because existing
watchdog and bridge callers share one active child. Services do not import that
facade. A supervisor can also own independent in-memory resources for testing or
another host composition. Observers run outside the resource mutex; recursive
start/stop calls during a lifecycle notification are ignored, while concurrent
requests serialize. Duplicate starts do not prepare configuration or emit hooks.

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

Failed launches do not subsequently emit `STOPPED` for the same exited child.
Shutdown emits `STOPPED` only after confirming exit; a child that remains alive
after the bounded termination attempt produces `FAILED`. The existing shutdown
call's return/exception contract remains unchanged.

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

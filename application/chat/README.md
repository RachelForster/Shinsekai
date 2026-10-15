# Chat runtime responsibilities

The public compatibility entry point is `runtime_process.py`. Its previous
implementation combined process ownership, launch preparation, transport
snapshots, history download capabilities, story persistence and command routing.
Characterization tests exercise the original entry points before extraction.

## Application lifecycle delivery

The application owns `LifecycleEvents` even when no plugins are installed or
plugin loading has not completed. Required application handlers run first; every
handler is attempted and their errors propagate as `LifecycleDispatchError`.
Optional observers, including the SDK plugin dispatcher, run afterward with
exception isolation. Observers see a required-handler error in their immutable
context when the originating context did not already contain an error.

`ChatProcessContext` now carries a unique `launch_id` alongside `session_id`.
Launch and resume pass the newly created stream identity explicitly, before the
bridge binds it as its active session. The supervisor monitors owned children
in the background and also detects exits during status reads. Exit delivery is
idempotent and occurs after the process gate and log are released; a stale exit
cannot release a replacement child's resources. Ordinary observer reentrancy
cannot recursively start or stop a process transition.

`ChatSessionLifecycle` directly executes ordered session effects, scoped to the
session and launch ID, before publishing session observations. The application
bus delivers process exit events to the session owner; session methods do not
route their own work or snapshot return values through the bus. SDK session observation hooks are
registered through `register_chat_session_hook`:

- `CONNECTED`: the transport producer is attached. Legacy synchronous/headless
  entry points retain their existing confirmation boundary at this milestone.
- `READY`: asynchronous initialization explicitly succeeded. React asynchronous
  launches enable mobile access and remember the confirmed history path here,
  rather than on child `STARTED`. Legacy `CONNECTED` does not claim model readiness.
- `CLOSING`: close the transport notification and stop mobile access. A normal
  stop captures its final snapshot after these effects and before deletion.
- `ENDED`: delete the owned stream and clear the owned story/session state.
- `FAILED`: attempt rollback of all owned session effects; an error in one
  cleanup step does not prevent the remaining steps, and failures remain visible.

Initialization cleanup releases its exact stream identity idempotently, while a
delayed exit or old close cannot clear a newer launch, even for the same session
ID. Bridge watchdog shutdown uses the same session lifecycle and unregisters its
application subscription afterward. Structured lifecycle diagnostics observe
events separately, recording identity, exit code and elapsed time without launch
configuration or mutable host state.

Child signalling/termination and process log release remain in the supervisor.
Conversation history saving remains in the child's ordered shutdown orchestration,
before plugin/memory shutdown hooks. None of these operations depends on optional
plugin observers.

| Module | Responsibility | Dependencies |
| --- | --- | --- |
| `runtime_process.py` | Compatibility entry points and default service wiring | Existing bridge state and host adapters |
| `process_supervisor.py` | Child/log ownership, serialized lifecycle, bounded termination | Process primitives, resource slots, observer callback |
| `launch_preparation.py` | Templates, configuration and trusted launch plan | Root/entrypoint callbacks and existing config helpers |
| `runtime_projection.py` | Snapshot composition, identity and media defaults | History callback, runtime status and story/mobile projections |
| `runtime_history.py` | History projection and expiring download capabilities | Path/read/name callbacks, clock and token factory |
| `runtime_story.py` | Story history persistence and branch coordination | History and story ports |
| `runtime_commands.py` | Registered command handlers and transport delivery policy | Ports and callbacks required by each handler group |
| `runtime_ports.py` | Consumed structural contracts and story callbacks | Standard library and SDK lifecycle types |

Handlers extend `ChatCommandRouter` through `register`; the router and shared
delivery policy do not need new command branches. Local handlers must explicitly
opt out of child transport. History, story, snapshot and process tests can supply
small substitutes without constructing the plugin host or frontend transport.

The supervisor owns its child and log directly. The composition root exposes
only the application entry points used by the bridge; stateless helpers are
imported from their defining modules. Tests replace service dependencies rather
than historical facade globals. Observers run outside the process resource
mutex. Recursive start/stop requests during notification are ignored, while
concurrent requests serialize. Duplicate starts do not prepare configuration or
emit hooks.

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

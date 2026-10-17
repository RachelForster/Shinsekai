# LLM conversation runtime

`LLMManager` remains the public entry point used by chat workers, story generation,
localization and plugins. Existing constructor arguments, `chat()` return values,
history attributes, hooks and `LLMAdapterFactory` import paths remain available.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| `LLMManager` | Dependency composition, user-input metadata and turn scope/cancellation |
| `ConversationHistory` | History mutation, prompt snapshots, hooks and compaction |
| `MessageJournal` | Message persistence; the file implementation preserves story interception |
| `ToolSession` | Tool groups, budgets, cooldown filtering and execution policy for one conversation |
| `RequestRunner` | Request snapshots, token estimates, bounded tool-pair recovery and request metrics |
| `ChatLoop` | Iterative stream/sync rounds, tool-result ordering and final-answer repair/persistence |
| `LLMAdapter` / `ResponseCodec` | Provider capabilities, response decoding and assistant replay metadata |
| `LLMAdapterFactory` | Built-in registration and construction; plugin registration still extends its registry |

The conversation loop consumes `ChatResponse` and `ResponseDelta`. It must not
inspect concrete provider types or read the process-wide configuration singleton.
Provider-specific wire formats belong to codecs selected by adapters. Existing
SDK adapters default to the OpenAI-compatible codec; Claude selects the Anthropic
codec. Plugins can override `response_codec` or the decoding methods without
modifying the manager. Public response types are exported by `sdk.adapters`.
Compaction and dialogue repair also use the adapter decoder. Overrides of the
facade's `add_message()` continue to observe user, assistant and tool messages.

`supports_streaming_tools` declares whether a provider can retain tool metadata in
a stream. The factory passes the selected provider into built-in adapters, so
Gemini fallback and unsupported parameters follow the actual adapter rather than
another conversation's settings. Adapter subclasses inherit and may extend
`supported_chat_params`.

## Dependency injection

New composition roots can supply these keyword-only dependencies:

- `tools`: a `ToolCatalog`; supply its matching `executor` as well.
- `executor`: a `ToolRunner` implementing execution and cooldown queries.
- `host`: a `ChatHost` limited to tool notification, confirmation and token estimates.
- `journal`: a `MessageJournal` receiving each committed message.
- `compactor`: a `HistoryCompactor` implementing token accounting and compaction.

The narrow protocols live in `ports.py`. History and tool policy are owned by
individual manager instances. Compatibility defaults retain the existing shared
tool registry/executor and SDK host callbacks in `runtime_defaults.py`; callers
that need isolation should inject their own dependencies. Legacy state attributes
are views of their owning component, avoiding duplicate mutable state.
Closing a returned stream before its first consumption releases the turn scope
without opening a provider connection. Tool follow-up rounds are iterative.

## Regression checks

Before changing behavior, run the manager characterization tests against the
existing implementation. `test_llm_manager_regression.py` exercises real manager
calls with provider-shaped responses, including fragmented tool calls, replay
metadata, cancellation, stream failures, risk denial, persistence and repair.

`test_llm_manager_contracts.py` checks dependency isolation, custom codecs, adapter
switching, late hook installation and long iterative tool loops.
`test/unit/sdk/test_llm_response.py` checks wire compatibility and stream cleanup.
The project architecture tests continue to enforce SDK and layer independence.

Run the focused tests, followed by the configured Python suite. Tests use canned
responses and mocked transports; live provider API behavior requires a separate
smoke test with configured credentials.

`pnpm verify:tauri-resources` and `pnpm verify:packaged-runtime` compare every
copied Python module in `ai/llm` and `sdk` with the source checkout. Missing modules
and stale SDK files fail verification before the application ships. Rebuild the
application resources together when updating an existing local build.

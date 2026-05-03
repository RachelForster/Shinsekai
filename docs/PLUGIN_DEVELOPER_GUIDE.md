# Plugin Developer Guide

## Part 1 — Overview

### What a plugin is

Plugins are ordinary Python packages under `plugins/<package>/`, loaded from `**data/config/plugins.yaml**`, and executed **in-process** with the host. They are **not** a security boundary.

### How the host uses your code

1. **Load** the manifest and import each `entry` → `PluginBase` subclass.
2. **Construct** plugins with `cls()` (no constructor arguments).
3. **Call** `initialize(register, plugin_root, host)` in **priority** order (lower `priority` runs first).
4. **Merge** everything you registered on `register` (`PluginCapabilityRegistry`, alias `PluginRegister`) into global factories, tool lists, and UI contribution lists — see `core/plugins/plugin_host.py` and `sdk/manager.py`.

You need a **full restart** after changing `plugins.yaml` (unlike MCP save-and-apply).

### Registry surface at a glance


| Method                          | What it registers                                          |
| ------------------------------- | ---------------------------------------------------------- |
| `register_llm_adapter`          | LLM backend class → `LLMAdapterFactory`                    |
| `register_tts_adapter`          | TTS backend class → `TTSAdapterFactory`                    |
| `register_asr_adapter`          | ASR backend class → `ASRAdapterFactory`                    |
| `register_t2i_adapter`          | T2I backend class → `T2IAdapterFactory`                    |
| `register_llm_tool`             | Callback `(ToolManager) -> None` for imperative tools      |
| `register_message_handler`      | Optional `MessageHandler` / `UIOutputMessageHandler`       |
| `register_user_input_trigger`   | Hook `trigger(emit_user_text)` for alternate input sources |
| `register_user_input_processor` | `(str) -> str | None` filter before `UserInputMessage`     |
| `register_settings_ui`          | Extra Settings sidebar page                                |
| `register_tools_tab`            | Extra tab under **Settings → Tools**                       |
| `register_chat_ui_widget`       | Chat window widget + placement hint                        |


**Host-only** (do **not** call from plugins): `set_settings_ui_plugin_context`, `clear_settings_ui_plugin_context`. The host wraps `initialize` so `SettingsUIContribution` / `ToolsTabContribution` pick up `plugin_id` / `plugin_version` when you leave those fields `None`.

---

## Part 2 — Details

### Manifest and `entry`

- **Path:** `data/config/plugins.yaml` — YAML **list** of dicts with at least `**entry`**, optional `**enabled**`.  
- **Explicit class (recommended):** `plugins.my_pkg.plugin:MyPkgPlugin`  
- **Module + `Plugin` attribute:** `plugins.my_pkg.plugin` expects `Plugin = class`.  
- **Other keys** in YAML become `PluginDescriptor.extra`; the host **does not** inject `extra` into `initialize` today — use `plugin_root` or files under `data/plugins/` for plugin state.

### UI contexts (read-only surfaces)


| Context                   | Where it appears                                              | What you get                                                                                                                                                                       |
| ------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PluginHostContext`       | `initialize(..., host=…)`                                     | UI language, voice language, font size, theme tint, **selected LLM/TTS labels** (no secrets), `project_data_dir`. **No** `ConfigManager`, **no** API keys, **no** global save API. |
| `PluginSettingsUIContext` | `SettingsUIContribution.build` / `ToolsTabContribution.build` | `host` snapshot + `template_dir_path`, `history_dir`, `character_names`, `background_names`.                                                                                       |
| `ChatUIContext`           | `ChatUIContribution.build`                                    | Safe chat state reads, queued UI updates, `on_*` event subscriptions, `submit_user_message` when the host bound it.                                                                |


Prefer these over raw Qt signals on internal windows.

### Adapter classes: schemas and “extra” kwargs

#### Where adapters show up, and who owns the parameters

Registering an adapter only adds a **class** to the host factories. **Users** choose the backend and fill in secrets/options in the **Settings** window (PySide). Those values are **not** stored in `plugins.yaml` or in your package tree by default.


| Kind    | Where users pick it (Settings UI)                                                                                                                                                                             | Persisted to disk (typical)                                                                                                                                                                                                      | Your responsibility as the plugin author                                                                                                                                                                                                                                                            |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **LLM** | **API 设定** tab — “LLM provider” combo (`llm_provider`). Labels are **case-sensitive** and must match your `register_llm_adapter("Exact Name", …)`. Same tab: API key, base URL, model id, streaming/sampling. | `**data/config/api.yaml`** (`ApiConfig`): shared LLM fields plus `**llm_extra_configs[<llm_provider>]**` — populated from your adapter’s `**get_config_schema()**` via dynamic form widgets in `ui/settings_ui/tabs/api_tab.py`. | Implement `get_config_schema()` (optional) and an `__init__` that accepts kwargs the host will pass (see `ConfigManager.merged_llm_factory_kwargs`). Do **not** expect to read API keys inside `PluginBase.initialize`; they are injected only when the adapter instance is constructed at runtime. |
| **TTS** | **API 设定** tab — TTS engine combo (internal value is a **lowercase** slug, e.g. `gpt-sovits`). Shared fields (SoVITS path/URL, etc.) live on the same page.                                                   | `**data/config/api.yaml`**: `tts_provider` / shared TTS columns plus `**tts_extra_configs[<slug>]**` from `**get_config_schema()**`.                                                                                             | Register with the **same** slug the combo uses (`register_tts_adapter("my-engine", …)` → factory lowercases). Match ctor parameters to `merged_tts_factory_kwargs`.                                                                                                                                 |
| **ASR** | **System**-side provider choice (`asr_provider`: Vosk / Whisper-class plugins, etc.). Extra per-backend fields appear under **API 设定** when that ASR class exposes `**get_config_schema()`**.                 | `**data/config/system_config.yaml**` for global mic/Whisper options (`asr_provider`, model size, device, …) + `**data/config/api.yaml**` → `**asr_extra_configs[<normalized_slug>]**` for schema-driven extras.                  | `register_asr_adapter` slug must match the normalized key the host uses when creating the adapter (`asr/asr_adapter.py`). Base ctor still receives `(language, callback, …)` from the host.                                                                                                         |
| **T2I** | **API 设定** — Comfy-style URL, workflow paths, node IDs, etc. The dynamic “extra” panel is currently wired to the built-in Comfy adapter’s schema in `api_tab.py`.                                             | `**data/config/api.yaml`**: `t2i_*` fields plus `**t2i_extra_configs**` (default engine key `"comfyui"` in the UI today).                                                                                                        | `register_t2i_adapter` keys are **lowercased**. For non-Comfy engines, users may need to edit `**t2i_extra_configs[<your_engine>]`** manually until the Settings UI grows a provider switch; ctor should still accept kwargs from `merged_t2i_factory_kwargs`.                                      |


**Summary:** Adapter tuning is **centralized** in `**api.yaml`** / `**system_config.yaml**`, edited through **Settings** and `ConfigManager`. You expose **fields** via `**get_config_schema()`** and **parameter names** on `__init__`; you normally **do not** ship a parallel config format for the same secrets. Optional plugin-specific data (licenses, experimental flags) can still go under `**plugin_root`** or a page you add with `register_settings_ui`.

- `**get_config_schema()**` — Optional per-provider fields rendered on **API 设定** (`type`, `label`, `default`, `secret`, `choices`, …). Empty `{}` adds no extra widgets.  
- **Factory merge** — Host builds adapters with `merged_*_factory_kwargs`: **base** kwargs from `api.yaml` / `system_config.yaml` plus `**llm_extra_configs` / `tts_extra_configs` / `asr_extra_configs` / `t2i_extra_configs`**, filtered by `config.adapter_extra_kwargs.filter_kwargs_for_ctor` (or full dict if `__init__` has `**kwargs`).  
- **Subclass** `sdk/adapters` ABCs and register the **class**, not an instance.

---

## `PluginCapabilityRegistry` — one example per `register_`*

### `register_llm_adapter(provider, adapter_cls)`

**Provider string** must match the **exact** LLM provider name the UI saves (e.g. `"Deepseek"`, `"ChatGPT"`).

```python
from sdk.adapters.llm import LLMAdapter
from sdk.register import PluginCapabilityRegistry


class EchoLLMAdapter(LLMAdapter):
    """Minimal demo: echo the last user message (ignores real API keys)."""

    def chat(self, messages: list, stream: bool = False, **kwargs):
        for m in reversed(messages or []):
            if isinstance(m, dict) and m.get("role") == "user":
                return m.get("content") or ""
        return "…"


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    register.register_llm_adapter("MyEchoLLM", EchoLLMAdapter)
```

Shippable adapters should honor `api_key`, `base_url`, `model`, streaming, and tool loops like the built-ins in `llm/llm_adapter.py`.

---

### `register_tts_adapter(provider, adapter_cls)`

**Provider** is resolved with `.lower()` (e.g. `"my-tts"`).

```python
from sdk.adapters.tts import TTSAdapter
from sdk.register import PluginCapabilityRegistry


class SilenceTTSAdapter(TTSAdapter):
    def generate_speech(self, text, file_path=None, **kwargs):
        return None

    def switch_model(self, model_info):
        return None


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    register.register_tts_adapter("my-silent-tts", SilenceTTSAdapter)
```

Align your real `__init__` signature with what `merged_tts_factory_kwargs` supplies.

---

### `register_asr_adapter(provider_slug, adapter_cls)`

**Slug** must match the normalized ASR provider in settings (`asr/asr_adapter.py`). **Base signature:** `__init__(self, language: str, callback: TranscriptionCallback, **optional_extras)`.

```python
from sdk.adapters.asr import ASRAdapter
from sdk.register import PluginCapabilityRegistry


class NoopAsrAdapter(ASRAdapter):
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def get_status(self) -> str:
        return "idle"

    def pause(self) -> None:
        return None

    def resume(self) -> None:
        return None


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    register.register_asr_adapter("my_noop_asr", NoopAsrAdapter)
```

---

### `register_t2i_adapter(provider, adapter_cls)`

**Provider** is stored **lowercased**.

```python
from typing import Any, Dict, Optional

from sdk.adapters.t2i import T2IAdapter
from sdk.register import PluginCapabilityRegistry


class StubT2IAdapter(T2IAdapter):
    def generate_image(
        self, prompt: str, file_path: Optional[str] = None, **kwargs
    ) -> Optional[str]:
        return None

    def switch_model(self, model_info: Dict[str, Any]) -> None:
        return None


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    register.register_t2i_adapter("my_stub_t2i", StubT2IAdapter)
```

---

### `register_llm_tool(registrar)`

**Prefer** module-level `@tool` from `sdk.tool_registry` (the host runs `apply_registered_tools` **before** these callbacks). Use `register_llm_tool` when you need **dynamic** registration based on `plugin_root` or config.

```python
from llm.tools.tool_manager import ToolManager
from sdk.register import PluginCapabilityRegistry


def _register_extra_tools(tm: ToolManager) -> None:
    def roll_report(sides: int = 6) -> str:
        """Pretend dice; returns a short English string for the LLM."""
        return f"Rolled {sides}-sided die (stub)."

    tm.register_function(roll_report, name="roll_report", description="Stub dice roll.")


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    register.register_llm_tool(_register_extra_tools)
```

---

### `register_message_handler(tts_handler=..., ui_handler=...)`

Extend the TTS pipeline (`MessageHandler` for `LLMDialogMessage`) and/or UI output (`UIOutputMessageHandler` for `TTSOutputMessage`). First handler with `can_handle` wins.

```python
from core.handlers.handler_registry import MessageHandler
from core.messaging.message import LLMDialogMessage
from sdk.register import PluginCapabilityRegistry


class LogDialogHandler(MessageHandler):
    def can_handle(self, msg: LLMDialogMessage) -> bool:
        return bool((msg.effect or "").strip())

    def handle(self, msg: LLMDialogMessage) -> None:
        # Replace with real side effects (assets, logging, etc.).
        print(f"[plugin] effect={msg.effect!r} speech={msg.speech!r}")


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    register.register_message_handler(tts_handler=LogDialogHandler())
```

---

### `register_user_input_trigger(trigger)`

Receive `emit_user_text: Callable[[str], None]` — call it when your custom source has text (hotkey bridge, serial port, etc.). Usually stash `emit_user_text` and invoke it from your wiring.

```python
from collections.abc import Callable

from sdk.register import PluginCapabilityRegistry


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    def trigger(emit_user_text: Callable[[str], None]) -> None:
        self._emit_user_text = emit_user_text  # save on plugin instance

    register.register_user_input_trigger(trigger)
```

`plugin_host.wire_user_input_plugins` passes the same `emit_user_text` used by the chat input path.

---

### `register_user_input_processor(processor)`

Return **new string** to continue the pipeline, or `**None`** to **drop** the message.

```python
from sdk.register import PluginCapabilityRegistry


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    def strip_or_abort(raw: str) -> str | None:
        text = (raw or "").strip()
        return text if text else None

    register.register_user_input_processor(strip_or_abort)
```

---

### `register_settings_ui(contribution)`

```python
from sdk.plugin_host_context import PluginSettingsUIContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import SettingsUIContribution


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    def build_page(ctx: PluginSettingsUIContext):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(f"Characters loaded: {len(ctx.character_names)}"))
        return w

    register.register_settings_ui(
        SettingsUIContribution(
            page_id="my_plugin.settings",
            nav_label="My plugin",
            build=build_page,
            order=120.0,
        )
    )
```

---

### `register_tools_tab(contribution)`

Same `PluginSettingsUIContext` builder as settings pages; appears under **Settings → Tools**.

```python
from sdk.plugin_host_context import PluginSettingsUIContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import ToolsTabContribution


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    def build_tools(ctx: PluginSettingsUIContext):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(f"Template dir: {ctx.template_dir_path}"))
        return w

    register.register_tools_tab(
        ToolsTabContribution(
            tab_id="my_plugin.tools",
            title="My tool",
            build=build_tools,
            order=80.0,
        )
    )
```

---

### `register_chat_ui_widget(contribution)`

`placement` is a host-defined hint (`"toolbar"`, `"overlay"`, `"input_row"`, …).

```python
from sdk.chat_ui_context import ChatUIContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import ChatUIContribution


def initialize(self, register: PluginCapabilityRegistry, plugin_root, host) -> None:
    def build_widget(ctx: ChatUIContext):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel(ctx.notification_hint() or "—")
        lay.addWidget(hint)
        _disconnect = ctx.on_notification_changed(lambda t: hint.setText(t or "—"))
        w.destroyed.connect(_disconnect)
        return w

    register.register_chat_ui_widget(
        ChatUIContribution(
            widget_id="my_plugin.notify_echo",
            placement="toolbar",
            build=build_widget,
            order=10.0,
        )
    )
```

---

## Worked example: manifest + settings + `@tool`

`**data/config/plugins.yaml**`

```yaml
- entry: plugins.example_demo.plugin:ExampleDemoPlugin
  enabled: true
```

`**plugins/example_demo/__init__.py**`

```python
"""example_demo plugin package."""
```

`**plugins/example_demo/plugin.py**`

```python
from __future__ import annotations

from pathlib import Path

from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext, PluginSettingsUIContext
from sdk.register import PluginCapabilityRegistry
from sdk.tool_registry import tool
from sdk.types import SettingsUIContribution


@tool(name="demo_ping", description="Return a fixed ping string for testing.")
def demo_ping() -> str:
    return "pong"


class ExampleDemoPlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "com.example.demo"

    @property
    def plugin_version(self) -> str:
        return "0.1.0"

    @property
    def plugin_name(self) -> str:
        return "Demo (example)"

    @property
    def priority(self) -> int:
        return 100

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        _ = plugin_root

        def build_settings(ctx: PluginSettingsUIContext):
            from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

            w = QWidget()
            layout = QVBoxLayout(w)
            layout.addWidget(QLabel(f"UI language: {ctx.host.ui_language}"))
            layout.addWidget(QLabel(f"Loaded characters: {len(ctx.character_names)}"))
            return w

        register.register_settings_ui(
            SettingsUIContribution(
                page_id="example_demo.settings",
                nav_label="Demo plugin",
                build=build_settings,
                order=500.0,
            )
        )
```

Restart the app after adding the YAML row. The model can call `**demo_ping**` when tools are enabled for your template.

---

## Scaffolding and publishing

From the repo root:

```bash
python -m sdk.cli create my_plugin_name
```

Add the printed `entry` to `data/config/plugins.yaml`, restart, and iterate. To list a plugin in the in-app catalog, publish a row to [Shinsekai-Plugin-Registry](https://github.com/RachelForster/Shinsekai-Plugin-Registry):

```bash
python -m sdk.cli registry-snippet --name "my_plugin_name" --author "You" \
  --repo owner/repo --description "..." --entry "my_plugin_name.plugin:MyPkgPlugin"
```

---

## Part 3 — Wrap-up

### Before you ship

- Stable `plugin_id` / semver `plugin_version`.  
- Document the exact `**entry**` string and any **provider keys** users must select in Settings.  
- Optional `requirements.txt`; note GPU / external binaries if needed.  
- Restart required after `plugins.yaml` changes.  
- Prefer `@tool` + `PluginSetingsUIContext` / `ChatUIContext` over reaching into host internals.

### Source map


| Topic                        | Location                                                     |
| ---------------------------- | ------------------------------------------------------------ |
| Plugin base                  | `sdk/plugin.py`                                              |
| Registry                     | `sdk/register.py`                                            |
| Contribution types           | `sdk/types.py`                                               |
| Host snapshot / settings ctx | `sdk/plugin_host_context.py`                                 |
| Chat UI ctx                  | `sdk/chat_ui_context.py`                                     |
| Adapter ABCs                 | `sdk/adapters/*.py`                                          |
| Plugin manager               | `sdk/manager.py`                                             |
| Host wiring                  | `core/plugins/plugin_host.py`                                |
| Extra ctor kwargs            | `config/adapter_extra_kwargs.py`, `config/config_manager.py` |
| CLI                          | `sdk/cli/`                                                   |


This guide stays aligned with `PluginCapabilityRegistry` in `sdk/register.py`; if APIs drift, treat that file as the source of truth.
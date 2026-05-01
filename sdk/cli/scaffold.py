"""Create ``plugins/<package>/`` skeleton aligned with :class:`sdk.plugin.PluginBase`."""

from __future__ import annotations

import re
from pathlib import Path

_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_package_name(name: str) -> str:
    if not _PACKAGE_RE.fullmatch(name.strip()):
        raise ValueError(
            "package must be snake_case: ^[a-z][a-z0-9_]*$ "
            "(example: my_screen_tool)"
        )
    return name.strip()


def package_to_class_suffix(package: str) -> str:
    return "".join(part.capitalize() for part in package.split("_"))


def write_plugin_project(
    *,
    root: Path,
    package: str,
    plugin_id: str,
    display_name: str,
    include_settings_ui: bool,
) -> Path:
    plugins_dir = root / "plugins"
    dest = plugins_dir / package
    if dest.exists():
        raise FileNotFoundError(f"already exists: {dest}")

    class_suffix = package_to_class_suffix(package)
    class_name = f"{class_suffix}Plugin"
    entry = f"plugins.{package}.plugin:{class_name}"

    plugins_dir.mkdir(parents=True, exist_ok=True)
    dest.mkdir(parents=False)

    (dest / "__init__.py").write_text(
        f'"""Plugin package ``{package}`` (Easy AI Desktop Assistant)."""\n',
        encoding="utf-8",
    )

    if include_settings_ui:
        plugin_body = _PLUGIN_WITH_SETTINGS.format(
            class_name=class_name,
            plugin_id=plugin_id,
            display_name=display_name,
            package=package,
            page_id=f"{package}.settings",
            priority=100,
        )
    else:
        plugin_body = _PLUGIN_MINIMAL.format(
            class_name=class_name,
            plugin_id=plugin_id,
            priority=100,
        )

    (dest / "plugin.py").write_text(plugin_body, encoding="utf-8")

    readme = _README.format(
        package=package,
        class_name=class_name,
        entry=entry,
        plugin_id=plugin_id,
        display_name=display_name,
    )
    (dest / "README.md").write_text(readme, encoding="utf-8")

    return dest


_PLUGIN_MINIMAL = '''from __future__ import annotations

from pathlib import Path

from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry


class {class_name}(PluginBase):
    """TODO: describe what this plugin does."""

    @property
    def plugin_id(self) -> str:
        return "{plugin_id}"

    @property
    def plugin_version(self) -> str:
        return "0.1.0"

    @property
    def priority(self) -> int:
        return {priority}

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        _ = register, plugin_root, host
        # Register capabilities via ``register`` (settings UI, tools, LLM tools, …).

    def shutdown(self) -> None:
        return None
'''

_PLUGIN_WITH_SETTINGS = '''from __future__ import annotations

from pathlib import Path

from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry
from sdk.types import SettingsUIContribution


class {class_name}(PluginBase):
    """TODO: describe what this plugin does."""

    @property
    def plugin_id(self) -> str:
        return "{plugin_id}"

    @property
    def plugin_version(self) -> str:
        return "0.1.0"

    @property
    def priority(self) -> int:
        return {priority}

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        _ = plugin_root, host

        def build_settings(plg):
            from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(QLabel("TODO: build settings using ``plg`` snapshot."))
            return w

        register.register_settings_ui(
            SettingsUIContribution(
                page_id="{page_id}",
                nav_label="{display_name}",
                build=build_settings,
                order=100.0,
            )
        )

    def shutdown(self) -> None:
        return None
'''

_README = """# {display_name}

Easy AI Desktop Assistant plugin (`plugin_id`: `{plugin_id}`).

## Manifest entry

Add to `data/config/plugins.yaml`:

```yaml
- entry: {entry}
  enabled: true
```

## Registry (`plugins.json`)

Publish to [Shinsekai-Plugin-Registry](https://github.com/RachelForster/Shinsekai-Plugin-Registry) using:

```bash
python -m sdk.cli registry-append --registry /path/to/Shinsekai-Plugin-Registry \\
  --name "{display_name}" --author "YOUR_NAME" --repo YOUR_ORG/{package} \\
  --description "Short Chinese or English summary." \\
  --entry "{package}.plugin:{class_name}"
```

(`entry` here is usually **without** the `plugins.` prefix; the desktop app may prepend it when installing.)

## Layout

- `plugin.py` — `{class_name}` implementing `PluginBase`
"""

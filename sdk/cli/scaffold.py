"""Create ``plugins/<package>/`` skeleton aligned with :class:`sdk.plugin.PluginBase`."""

from __future__ import annotations

import re
from pathlib import Path

from sdk.file_transactions import atomic_write_text
from sdk.path_contract import (
    managed_child_path,
    require_directory_without_links,
    require_symlink_free_absolute_path,
)

_PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_package_name(name: str) -> str:
    if name != name.strip() or not _PACKAGE_RE.fullmatch(name):
        raise ValueError(
            "package must be snake_case: ^[a-z][a-z0-9_]*$ "
            "(example: my_screen_tool)"
        )
    return name


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
    package = validate_package_name(package)
    safe_root = require_symlink_free_absolute_path(
        root,
        field="plugin scaffold root",
    )
    plugins_dir = managed_child_path(
        safe_root,
        "plugins",
        field="plugin scaffold directory",
    )
    dest = managed_child_path(
        plugins_dir,
        package,
        field="plugin package name",
    )
    if dest.exists():
        raise FileNotFoundError(f"already exists: {dest}")

    class_suffix = package_to_class_suffix(package)
    class_name = f"{class_suffix}Plugin"
    entry = f"plugins.{package}.plugin:{class_name}"

    plugins_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir = require_directory_without_links(
        plugins_dir,
        field="plugin scaffold directory",
    )
    dest.mkdir(parents=False)
    dest = require_directory_without_links(
        dest,
        field="plugin package directory",
    )

    atomic_write_text(
        managed_child_path(dest, "__init__.py", field="plugin scaffold filename"),
        f'"""Plugin package ``{package}`` (Easy AI Desktop Assistant)."""\n',
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

    atomic_write_text(
        managed_child_path(dest, "plugin.py", field="plugin scaffold filename"),
        plugin_body,
    )

    readme = _README.format(
        package=package,
        class_name=class_name,
        entry=entry,
        plugin_id=plugin_id,
        display_name=display_name,
    )
    atomic_write_text(
        managed_child_path(dest, "README.md", field="plugin scaffold filename"),
        readme,
    )

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
from sdk.types import FrontendConfigContribution


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

        values = {{"enabled": True}}

        register.register_frontend_config(
            FrontendConfigContribution(
                page_id="{page_id}",
                title="{display_name}",
                schema=[
                    {{
                        "id": "main",
                        "title": "Settings",
                        "fields": [
                            {{"key": "enabled", "type": "boolean", "label": "Enabled"}}
                        ],
                    }}
                ],
                load_values=lambda: dict(values),
                save_values=lambda incoming: values.update(incoming),
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

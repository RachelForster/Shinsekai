from types import SimpleNamespace

from core.plugins.registry_catalog import RegistryPluginRecord
from frontend_bridge_core.plugin_catalog import (
    _display_title_for_offline_plugin_entry,
    _plugin_registry_rows,
    _resolve_loaded_plugin_for_manifest_entry,
)


class DemoPlugin:
    pass


def test_display_title_for_offline_plugin_entry_uses_class_or_module_tail():
    assert _display_title_for_offline_plugin_entry("plugins.demo.plugin:DemoPlugin") == "DemoPlugin"
    assert _display_title_for_offline_plugin_entry("plugins.demo.plugin") == "plugin"
    assert _display_title_for_offline_plugin_entry("Demo") == "Demo"


def test_resolve_loaded_plugin_for_manifest_entry_matches_full_entry_or_module():
    plugin = DemoPlugin()
    manager = SimpleNamespace(plugins=[plugin])
    full_entry = f"{DemoPlugin.__module__}:{DemoPlugin.__qualname__}"

    assert _resolve_loaded_plugin_for_manifest_entry(full_entry, manager) is plugin
    assert _resolve_loaded_plugin_for_manifest_entry(DemoPlugin.__module__, manager) is plugin
    assert _resolve_loaded_plugin_for_manifest_entry("missing.module:Plugin", manager) is None
    assert _resolve_loaded_plugin_for_manifest_entry(full_entry, None) is None


def test_resolve_loaded_plugin_for_manifest_entry_handles_manager_errors():
    class BrokenManager:
        @property
        def plugins(self):
            raise RuntimeError("unavailable")

    assert _resolve_loaded_plugin_for_manifest_entry("anything", BrokenManager()) is None


def test_plugin_registry_rows_expose_market_metadata(monkeypatch):
    record = RegistryPluginRecord(
        id="demo",
        name="demo",
        display_name="Demo Plugin",
        author="Tester",
        repo="owner/demo",
        description="Long detail text",
        short_description="Short card text",
        entry="plugins.demo.plugin:DemoPlugin",
        version="v0.1.0",
        shinsekai_version=">=2.0.0",
        source_url="https://github.com/owner/demo",
        readme_url="https://raw.githubusercontent.com/owner/demo/main/README.md",
        download_url="https://plugins.example.invalid/plugins/demo.zip",
        sha256="abc123",
        commit_sha="deadbeef",
        size=4096,
        updated_at="2026-06-06T00:00:00Z",
        tags=["utility", "ai"],
        logo="https://plugins.example.invalid/plugins/demo/logo.png",
        stars=12,
        forks=3,
        social_link="https://github.com/tester",
        package_source="r2",
        package_url="https://plugins.example.invalid/plugins/demo.zip",
        package_sha256="abc123",
        package_size=4096,
        package_r2_key="plugins/owner/demo/v0.1.0/demo.zip",
        security_scan={"llm_agent": {"pass": True}},
    )

    monkeypatch.setattr("core.plugins.registry_catalog.fetch_registry_plugins", lambda: [record])
    monkeypatch.setattr("core.plugins.registry_download.load_downloaded_repos", lambda: {"owner/demo"})
    monkeypatch.setattr(
        "frontend_bridge_core.plugin_catalog._plugin_rows",
        lambda: [{"entry": "plugins.demo.plugin:DemoPlugin"}],
    )

    rows = _plugin_registry_rows()

    assert rows == [
        {
            "author": "Tester",
            "commitSha": "deadbeef",
            "description": "Long detail text",
            "displayName": "Demo Plugin",
            "downloadUrl": "https://plugins.example.invalid/plugins/demo.zip",
            "downloaded": True,
            "entry": "plugins.demo.plugin:DemoPlugin",
            "forks": 3,
            "id": "demo",
            "installed": True,
            "logo": "https://plugins.example.invalid/plugins/demo/logo.png",
            "name": "demo",
            "packageR2Key": "plugins/owner/demo/v0.1.0/demo.zip",
            "packageSha256": "abc123",
            "packageSize": 4096,
            "packageSource": "r2",
            "packageUrl": "https://plugins.example.invalid/plugins/demo.zip",
            "readmeUrl": "https://raw.githubusercontent.com/owner/demo/main/README.md",
            "repo": "owner/demo",
            "review": None,
            "securityScan": {"llm_agent": {"pass": True}},
            "sha256": "abc123",
            "shinsekaiVersion": ">=2.0.0",
            "shortDescription": "Short card text",
            "size": 4096,
            "socialLink": "https://github.com/tester",
            "sourceUrl": "https://github.com/owner/demo",
            "stars": 12,
            "tags": ["utility", "ai"],
            "trustLevel": "community",
            "updatedAt": "2026-06-06T00:00:00Z",
            "verified": False,
            "version": "v0.1.0",
        }
    ]

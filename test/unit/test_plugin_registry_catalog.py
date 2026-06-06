from urllib.error import URLError

from core.plugins.registry_catalog import (
    DEFAULT_REGISTRY_JSON_URL,
    LEGACY_REGISTRY_JSON_URL,
    fetch_registry_plugins,
    parse_registry_plugins,
)


def test_default_registry_url_points_to_upstream_generated_cache():
    assert DEFAULT_REGISTRY_JSON_URL == (
        "https://raw.githubusercontent.com/RachelForster/Shinsekai-Plugin-Registry/main/plugin_cache_original.json"
    )
    assert LEGACY_REGISTRY_JSON_URL == (
        "https://raw.githubusercontent.com/RachelForster/Shinsekai-Plugin-Registry/main/plugins.json"
    )


def test_fetch_registry_plugins_falls_back_from_generated_to_legacy(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise URLError("generated registry offline")
        return FakeResponse(
            b'{"demo": {"name": "demo", "repo": "owner/demo", "entry": "demo.plugin:DemoPlugin"}}'
        )

    monkeypatch.setattr("core.plugins.registry_catalog.urlopen", fake_urlopen)

    records = fetch_registry_plugins(timeout_sec=1)

    assert [record.name for record in records] == ["demo"]
    assert calls == [DEFAULT_REGISTRY_JSON_URL, LEGACY_REGISTRY_JSON_URL]


def test_parse_registry_plugins_accepts_market_object_payload():
    records = parse_registry_plugins(
        {
            "shinsekai-plugin-demo": {
                "display_name": "Demo Plugin",
                "desc": "Short card text",
                "description": "Long detail text",
                "author": "Plugin Author",
                "repo": "https://github.com/example/shinsekai-plugin-demo",
                "entry": "plugins.demo.plugin:DemoPlugin",
                "version": "v0.1.0",
                "shinsekai_version": ">=2.0.0",
                "download_url": "https://plugins.example.invalid/plugins/demo.zip",
                "sha256": "abc123",
                "commit_sha": "deadbeef",
                "size": "4096",
                "updated_at": "2026-06-06T00:00:00Z",
                "tags": "utility, ai",
                "logo": "https://plugins.example.invalid/plugins/demo/logo.png",
                "stars": "12",
                "forks": 3,
                "social_link": "https://github.com/example",
                "sec_scan": {"llm_agent": {"pass": True}},
            }
        }
    )

    assert len(records) == 1
    rec = records[0]
    assert rec.id == "shinsekai-plugin-demo"
    assert rec.name == "shinsekai-plugin-demo"
    assert rec.display_name == "Demo Plugin"
    assert rec.short_description == "Short card text"
    assert rec.description == "Long detail text"
    assert rec.repo == "https://github.com/example/shinsekai-plugin-demo"
    assert rec.version == "v0.1.0"
    assert rec.shinsekai_version == ">=2.0.0"
    assert rec.download_url == "https://plugins.example.invalid/plugins/demo.zip"
    assert rec.package_url == rec.download_url
    assert rec.sha256 == "abc123"
    assert rec.package_sha256 == "abc123"
    assert rec.commit_sha == "deadbeef"
    assert rec.size == 4096
    assert rec.package_size == 4096
    assert rec.tags == ["utility", "ai"]
    assert rec.logo.endswith("/logo.png")
    assert rec.stars == 12
    assert rec.forks == 3
    assert rec.security_scan == {"llm_agent": {"pass": True}}


def test_parse_registry_plugins_accepts_nested_package_payload_and_legacy_array():
    records = parse_registry_plugins(
        {
            "schema": 2,
            "plugins": [
                {
                    "id": "demo",
                    "name": "demo",
                    "display_name": "Demo",
                    "repo": "owner/demo",
                    "package": {
                        "source": "r2",
                        "url": "https://plugins.example.invalid/plugins/demo.zip",
                        "sha256": "def456",
                        "size": 2048,
                        "r2_key": "plugins/owner/demo/v0.1.0/demo.zip",
                    },
                },
                {
                    "name": "legacy",
                    "repo": "owner/legacy",
                    "description": "Old shape",
                    "entry": "legacy.plugin:Legacy",
                },
            ],
        }
    )

    assert records[0].id == "demo"
    assert records[0].package_source == "r2"
    assert records[0].package_url == "https://plugins.example.invalid/plugins/demo.zip"
    assert records[0].download_url == records[0].package_url
    assert records[0].package_r2_key == "plugins/owner/demo/v0.1.0/demo.zip"
    assert records[1].id == "legacy"
    assert records[1].display_name == "legacy"
    assert records[1].package_url == ""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

import pytest

from core.plugins.publisher.metadata import scan_local_plugin
from core.plugins.publisher.submission import build_issue_url, submission_json
from core.plugins.publisher.validate import PluginSubmissionError, normalize_submission
from frontend_bridge_core.plugin_publisher import (
    _build_plugin_submission_issue_url,
    _validate_plugin_submission,
)


def valid_submission(**overrides):
    payload = {
        "display_name": "Demo Plugin",
        "desc": "Short plugin description.",
        "author": "sample-owner",
        "repo": "https://github.com/sample-owner/demo-plugin",
        "tags": ["utility", "voice"],
        "social_link": "https://github.com/sample-owner",
    }
    payload.update(overrides)
    return payload


def issue_form_json(issue_url):
    query = parse_qs(urlparse(issue_url).query)
    body = query["plugin-info"][0]
    json_text = body.split("\n", 1)[1].rsplit("\n```", 1)[0]
    return json.loads(json_text)


def test_scan_local_plugin_infers_metadata_and_sanitizes_hyphenated_entry():
    with TemporaryDirectory(prefix="plugin-publisher-", dir=Path.cwd()) as temp_dir:
        plugin_root = Path(temp_dir) / "demo-plugin"
        plugin_root.mkdir()
        (plugin_root / "README.md").write_text(
            "# Demo Plugin\n\nShort plugin description.\n\nMore details stay out of desc.\n",
            encoding="utf-8",
        )
        (plugin_root / "plugin.py").write_text(
            "class DemoPublisherPlugin(PluginBase):\n    pass\n",
            encoding="utf-8",
        )
        git_dir = plugin_root / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n    url = git@github.com:sample-owner/demo-plugin.git\n',
            encoding="utf-8",
        )

        result = scan_local_plugin(plugin_root)

    assert result["display_name"] == "Demo Plugin"
    assert result["desc"] == "Short plugin description."
    assert result["author"] == "sample-owner"
    assert result["repo"] == "https://github.com/sample-owner/demo-plugin"
    assert result["entry"] == "plugins.demo_plugin.plugin:DemoPublisherPlugin"
    assert "-" not in result["entry"].split(":", 1)[0]
    assert result["tags"] == []


def test_scan_local_plugin_tolerates_duplicate_git_config_options():
    with TemporaryDirectory(prefix="plugin-publisher-", dir=Path.cwd()) as temp_dir:
        plugin_root = Path(temp_dir) / "demo-plugin"
        plugin_root.mkdir()
        (plugin_root / "plugin.py").write_text(
            "class DemoPublisherPlugin(PluginBase):\n    pass\n",
            encoding="utf-8",
        )
        git_dir = plugin_root / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            "\n".join(
                [
                    '[remote "origin"]',
                    "    url = git@github.com:sample-owner/demo-plugin.git",
                    '[branch "feat/refactor-chat-ui"]',
                    "    vscode-merge-base = upstream/main",
                    "    vscode-merge-base = upstream/main",
                ]
            ),
            encoding="utf-8",
        )

        result = scan_local_plugin(plugin_root)

    assert result["repo"] == "https://github.com/sample-owner/demo-plugin"


def test_scan_local_plugin_normalizes_root_directory_name_to_lowercase_entry():
    with TemporaryDirectory(prefix="plugin-publisher-", dir=Path.cwd()) as temp_dir:
        plugin_root = Path(temp_dir) / "Shinsekai-Plugin-Market"
        plugin_root.mkdir()
        (plugin_root / "plugin.py").write_text(
            "class MarketPlugin(PluginBase):\n    pass\n",
            encoding="utf-8",
        )

        result = scan_local_plugin(plugin_root)

    assert result["entry"] == "plugins.shinsekai_plugin_market.plugin:MarketPlugin"


def test_normalize_submission_normalizes_repo_url_and_serializes_contract_json():
    payload = valid_submission(
        display_name="  Demo Plugin  ",
        repo="https://github.com/sample-owner/demo-plugin.git",
        tags="utility, voice, tools",
        social_link="  https://github.com/sample-owner  ",
    )

    normalized = normalize_submission(payload)

    expected = {
        "display_name": "Demo Plugin",
        "desc": "Short plugin description.",
        "author": "sample-owner",
        "repo": "https://github.com/sample-owner/demo-plugin",
        "tags": ["utility", "voice", "tools"],
        "social_link": "https://github.com/sample-owner",
    }
    assert normalized == expected
    assert json.loads(submission_json(payload)) == expected


def test_normalize_submission_drops_entry_from_legacy_payload():
    payload = valid_submission(entry="plugins.demo_plugin.plugin:DemoPlugin")

    normalized = normalize_submission(payload)

    assert "entry" not in normalized
    assert "entry" not in json.loads(submission_json(payload))


def test_normalize_submission_keeps_only_basic_issue_fields():
    payload = valid_submission(
        entry="plugins.demo_plugin.plugin:DemoPlugin",
        logo="https://example.invalid/logo.png",
        plugin_name="demo-plugin",
        lowest_shinsekai_version=">=2.0.0",
        version="1.2.3",
    )

    normalized = normalize_submission(payload)

    assert set(normalized) == {
        "display_name",
        "desc",
        "author",
        "social_link",
        "repo",
        "tags",
        "lowest_shinsekai_version",
    }
    assert normalized["lowest_shinsekai_version"] == ">=2.0.0"
    assert "entry" not in normalized
    assert "logo" not in normalized
    assert "plugin_name" not in normalized
    assert "version" not in normalized
    assert json.loads(submission_json(payload)) == normalized


def test_normalize_submission_accepts_legacy_shinsekai_version_alias():
    payload = valid_submission(shinsekai_version=">=2.0.0")

    normalized = normalize_submission(payload)

    assert normalized["lowest_shinsekai_version"] == ">=2.0.0"
    assert "shinsekai_version" not in normalized


@pytest.mark.parametrize("field", ("display_name", "desc", "author", "repo"))
def test_normalize_submission_rejects_missing_required_fields(field):
    payload = valid_submission(**{field: " "})

    with pytest.raises(PluginSubmissionError, match=rf"{field} .*required"):
        normalize_submission(payload)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"desc": "x" * 201}, "desc must be 200 characters or fewer"),
        ({"tags": ["one", "two", "three", "four", "five", "six"]}, "at most 5 items"),
        ({"repo": "http://github.com/sample-owner/demo-plugin"}, "must use https://github.com"),
    ],
)
def test_normalize_submission_rejects_invalid_bounds_and_repo_urls(overrides, message):
    with pytest.raises(PluginSubmissionError, match=message):
        normalize_submission(valid_submission(**overrides))


def test_build_issue_url_defaults_to_upstream_registry(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_PLUGIN_SUBMIT_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PLUGIN_SUBMIT_TARGET", raising=False)

    issue_url = build_issue_url(valid_submission())
    parsed = urlparse(issue_url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "github.com"
    assert parsed.path == "/RachelForster/Shinsekai-Plugin-Registry/issues/new"
    assert query["template"] == ["PLUGIN_PUBLISH.yml"]
    assert query["title"] == ["[Plugin] Demo Plugin"]
    assert "body" not in query
    assert issue_form_json(issue_url) == normalize_submission(valid_submission())


def test_build_issue_url_removes_legacy_body_parameter():
    issue_url = build_issue_url(
        valid_submission(),
        base_url=(
            "https://github.com/example-org/example-registry/issues/new"
            "?template=PLUGIN_PUBLISH.yml&body=legacy-body&labels=plugin-publish"
        ),
    )
    query = parse_qs(urlparse(issue_url).query)

    assert "body" not in query
    assert query["labels"] == ["plugin-publish"]
    assert issue_form_json(issue_url) == normalize_submission(valid_submission())


def test_build_issue_url_targets_staging_registry_fork_when_configured(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_PLUGIN_SUBMIT_URL", raising=False)
    monkeypatch.setenv("SHINSEKAI_PLUGIN_SUBMIT_TARGET", "staging")

    issue_url = build_issue_url(valid_submission())

    assert urlparse(issue_url).path == "/End0rph1nww/Shinsekai-Plugin-Registry/issues/new"


def test_frontend_bridge_validate_submission_returns_frontend_payload():
    result = _validate_plugin_submission(valid_submission())
    expected = normalize_submission(valid_submission())

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["submission"] == expected
    assert json.loads(result["json"]) == expected

    invalid = _validate_plugin_submission(valid_submission(display_name=""))
    assert invalid["ok"] is False
    assert invalid["errors"] == ["display_name is required and must be a non-empty string."]
    assert "json" not in invalid
    assert "submission" not in invalid


def test_frontend_bridge_build_issue_url_returns_frontend_payload(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_PLUGIN_SUBMIT_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_PLUGIN_SUBMIT_TARGET", raising=False)

    result = _build_plugin_submission_issue_url(valid_submission())
    expected = normalize_submission(valid_submission())

    assert result["submission"] == expected
    assert json.loads(result["json"]) == expected
    assert result["submitUrl"].startswith(
        "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new"
    )
    assert result["issueUrl"].startswith(
        "https://github.com/RachelForster/Shinsekai-Plugin-Registry/issues/new"
    )
    assert issue_form_json(result["issueUrl"]) == expected

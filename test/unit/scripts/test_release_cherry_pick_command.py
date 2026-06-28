import importlib
import sys

import pytest


def load_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REPO", "owner/repo")
    monkeypatch.setenv("ISSUE_NUMBER", "123")
    monkeypatch.setenv("COMMENT_BODY", "/cherry-pick")
    monkeypatch.setenv("COMMENT_AUTHOR", "maintainer")
    monkeypatch.setenv("AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("RUN_ID", "1")
    sys.modules.pop("scripts.release_cherry_pick_command", None)
    return importlib.import_module("scripts.release_cherry_pick_command")


def test_resolve_inputs_searches_tracking_issue_from_resolved_branch(monkeypatch):
    module = load_module(monkeypatch)
    issue = {
        "number": 123,
        "title": "[RC v2.1.0-rc.1] crash",
        "body": "\n".join(
            [
                "- Parent release: v2.1.0",
                "- Fix commit on `main`: abcdef1234567890",
            ]
        ),
    }
    tracking_issue = {
        "number": 456,
        "title": "Release tracking: v2.1.0",
        "body": "- Release branch: `release/2.1`",
    }
    searched = []

    monkeypatch.setattr(module, "fetch_issue", lambda number: issue)
    monkeypatch.setattr(module, "fetch_parent_issue", lambda number: None)

    def fake_search_tracking_issue(branch):
        searched.append(branch)
        return tracking_issue

    monkeypatch.setattr(module, "search_tracking_issue", fake_search_tracking_issue)

    commit, branch, parent = module.resolve_inputs()

    assert commit == "abcdef1234567890"
    assert branch == "release/2.1"
    assert parent == tracking_issue
    assert searched == ["release/2.1"]


def test_resolve_inputs_uses_release_tracking_parent_fields(monkeypatch):
    module = load_module(monkeypatch)
    monkeypatch.setenv("COMMENT_BODY", "/cherry-pick abcdef1")
    module.COMMENT_BODY = "/cherry-pick abcdef1"
    issue = {"number": 123, "title": "Bug", "body": ""}
    parent = {
        "number": 456,
        "title": "Release tracking: v2.2.0",
        "body": "- Release branch: `release/2.2`",
    }
    search_calls = []

    monkeypatch.setattr(module, "fetch_issue", lambda number: issue)
    monkeypatch.setattr(module, "fetch_parent_issue", lambda number: parent)
    monkeypatch.setattr(
        module,
        "search_tracking_issue",
        lambda branch: search_calls.append(branch),
    )

    commit, branch, resolved_parent = module.resolve_inputs()

    assert commit == "abcdef1"
    assert branch == "release/2.2"
    assert resolved_parent == parent
    assert search_calls == []


def test_missing_branch_error_includes_template_hint(monkeypatch):
    module = load_module(monkeypatch)
    issue = {
        "number": 123,
        "title": "Bug",
        "body": "- Fix commit on `main`: abcdef1",
    }

    monkeypatch.setattr(module, "fetch_issue", lambda number: issue)
    monkeypatch.setattr(module, "fetch_parent_issue", lambda number: None)

    with pytest.raises(ValueError) as exc_info:
        module.resolve_inputs()

    message = str(exc_info.value)
    assert "No release branch found" in message
    assert "- Parent release: v2.1.0" in message
    assert "docs/RELEASE_PROCESS_zh-CN.md#5-bug-修复与-cherry-pick" in message


def test_run_rejects_unsupported_subprocess_command(monkeypatch):
    module = load_module(monkeypatch)

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(module.subprocess, "run", fail_run)

    with pytest.raises(ValueError, match="Refused subprocess command"):
        module.run(["python", "-c", "print(1)"])


def test_run_rejects_unsupported_subcommand(monkeypatch):
    module = load_module(monkeypatch)

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(module.subprocess, "run", fail_run)

    with pytest.raises(ValueError, match="Refused subprocess command"):
        module.run(["git", "remote", "-v"])

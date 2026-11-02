import subprocess

from scripts import presubmit


def test_pre_push_commit_range_excludes_commits_reachable_from_any_remote(monkeypatch):
    calls: list[list[str]] = []

    def fake_git(args, capture_output=False):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="local-commit\n", stderr="")

    monkeypatch.setattr(presubmit, "git", fake_git)

    commits = presubmit.commits_from_pre_push_input(
        "origin",
        "refs/heads/topic local-sha refs/heads/topic remote-sha\n",
    )

    assert commits == ["local-commit"]
    assert calls == [["rev-list", "remote-sha..local-sha", "--not", "--remotes"]]


def test_pre_push_new_branch_excludes_commits_reachable_from_any_remote(monkeypatch):
    calls: list[list[str]] = []

    def fake_git(args, capture_output=False):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="local-commit\n", stderr="")

    monkeypatch.setattr(presubmit, "git", fake_git)

    commits = presubmit.commits_from_pre_push_input(
        "origin",
        f"refs/heads/topic local-sha refs/heads/topic {presubmit.ZERO_SHA}\n",
    )

    assert commits == ["local-commit"]
    assert calls == [["rev-list", "local-sha", "--not", "--remotes"]]

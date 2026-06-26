import json
import os
import re
import subprocess
import sys
from urllib.parse import quote


REPO = os.environ["REPO"]
COMMENT_BODY = os.environ.get("COMMENT_BODY") or ""
COMMENT_AUTHOR = os.environ.get("COMMENT_AUTHOR") or ""
AUTHOR_ASSOCIATION = (os.environ.get("AUTHOR_ASSOCIATION") or "").upper()
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])
RUN_ID = os.environ.get("RUN_ID") or "manual"

ALLOWED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(command)}", file=sys.stderr)
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def gh_api(*args: str, input_json: dict | None = None, check: bool = True) -> str:
    command = ["gh", "api", *args]
    payload = None if input_json is None else json.dumps(input_json)
    result = subprocess.run(
        command,
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        print(f"gh api failed: {' '.join(command[2:])}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def comment(body: str) -> None:
    gh_api(
        f"repos/{REPO}/issues/{ISSUE_NUMBER}/comments",
        "--method",
        "POST",
        "--input",
        "-",
        input_json={"body": body},
    )


def fetch_issue(number: int) -> dict:
    return json.loads(gh_api(f"repos/{REPO}/issues/{number}"))


def fetch_parent_issue(number: int) -> dict | None:
    result = run(["gh", "api", f"repos/{REPO}/issues/{number}/parent"], check=False)
    if result.returncode == 0:
        return json.loads(result.stdout)
    if "not found" in result.stderr.lower() or "404" in result.stderr:
        return None
    print(result.stderr, file=sys.stderr)
    raise SystemExit(result.returncode)


def parse_command(body: str) -> tuple[str | None, str | None]:
    first_line = (body or "").splitlines()[0].strip()
    match = re.match(
        r"^/(?:cherry-pick|cherrypick)(?:\s+(.+))?$",
        first_line,
        flags=re.IGNORECASE,
    )
    if not match:
        raise SystemExit(0)
    args = (match.group(1) or "").split()
    commit = None
    branch = None
    for arg in args:
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", arg):
            commit = arg
        elif re.fullmatch(r"release/[A-Za-z0-9._-]+", arg):
            branch = arg
        else:
            raise ValueError(
                "Usage: `/cherry-pick [commit-sha] [release/x.y]`. "
                "If omitted, the workflow reads them from the release issue fields."
            )
    return commit, branch


def parse_field(body: str, field: str) -> str | None:
    match = re.search(
        rf"^\s*-\s*{re.escape(field)}\s*:\s*(.+?)\s*$",
        body or "",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    value = match.group(1).strip()
    return value if value and value.upper() != "TBD" else None


def parse_commit_from_issue(issue: dict) -> str | None:
    value = parse_field(issue.get("body") or "", "Fix commit on `main`")
    if not value:
        return None
    match = re.search(r"\b([0-9a-fA-F]{7,40})\b", value)
    return match.group(1) if match else None


def release_branch_from_version(version: str) -> str | None:
    match = re.search(r"v?(\d+)\.(\d+)(?:\.\d+)?", version or "")
    if not match:
        return None
    return f"release/{match.group(1)}.{match.group(2)}"


def parse_branch_from_issue(issue: dict) -> str | None:
    body = issue.get("body") or ""
    for field in ("Release branch", "Cherry-picked to release branch"):
        value = parse_field(body, field)
        if value:
            match = re.search(r"\brelease/[A-Za-z0-9._-]+\b", value)
            if match:
                return match.group(0)

    for field in ("Parent release", "Found in RC", "Version", "Current RC tag"):
        value = parse_field(body, field)
        branch = release_branch_from_version(value or "")
        if branch:
            return branch

    branch = release_branch_from_version(issue.get("title") or "")
    if branch:
        return branch
    return None


def search_tracking_issue(release_branch: str) -> dict | None:
    version = release_branch.split("/", 1)[1]
    query = f'repo:{REPO} is:issue in:title "Release tracking: v{version}"'
    output = gh_api(f"search/issues?q={quote(query, safe='')}&per_page=10")
    for item in json.loads(output).get("items", []):
        if (item.get("title") or "").startswith(f"Release tracking: v{version}"):
            return fetch_issue(int(item["number"]))
    return None


def resolve_inputs() -> tuple[str, str, dict | None]:
    commit, branch = parse_command(COMMENT_BODY)
    issue = fetch_issue(ISSUE_NUMBER)
    parent = fetch_parent_issue(ISSUE_NUMBER)
    parent = (
        parent
        if parent and (parent.get("title") or "").startswith("Release tracking:")
        else None
    )

    if commit is None:
        commit = parse_commit_from_issue(issue)
    if commit is None and parent is not None:
        commit = parse_commit_from_issue(parent)

    if branch is None:
        branch = parse_branch_from_issue(issue)
    if branch is None and parent is not None:
        branch = parse_branch_from_issue(parent)
    if branch is None and commit:
        inferred = parse_branch_from_issue(issue)
        parent = search_tracking_issue(inferred) if inferred else parent
        if parent is not None:
            branch = parse_branch_from_issue(parent)

    if not commit:
        raise ValueError(
            "No commit SHA found. Use `/cherry-pick <commit-sha>` or fill the "
            "`Fix commit on main` field on this issue."
        )
    if not branch:
        raise ValueError(
            "No release branch found. Use `/cherry-pick <commit-sha> release/x.y` "
            "or fill release linkage fields."
        )
    if not re.fullmatch(r"release/[A-Za-z0-9._-]+", branch):
        raise ValueError(f"Refused non-release target branch: `{branch}`")
    return commit, branch, parent


def ensure_maintainer() -> None:
    if AUTHOR_ASSOCIATION in ALLOWED_ASSOCIATIONS:
        return
    response = gh_api(
        f"repos/{REPO}/collaborators/{COMMENT_AUTHOR}/permission",
        check=False,
    )
    permission = json.loads(response or "{}").get("permission", "")
    if permission in {"admin", "maintain", "write"}:
        return
    raise PermissionError(
        f"Sorry @{COMMENT_AUTHOR}, only maintainers can use `/cherry-pick`."
    )


def create_cherry_pick_pr(commit: str, release_branch: str, parent: dict | None) -> str:
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ]
    )

    run(
        [
            "git",
            "fetch",
            "origin",
            f"+refs/heads/{release_branch}:refs/remotes/origin/{release_branch}",
            "+refs/heads/main:refs/remotes/origin/main",
        ]
    )
    rev_parse = run(["git", "rev-parse", "--verify", f"{commit}^{{commit}}"], check=False)
    if rev_parse.returncode != 0 and re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        run(["git", "fetch", "origin", commit], check=False)
        rev_parse = run(
            ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
            check=False,
        )
    if rev_parse.returncode != 0:
        comment(
            f"Cherry-pick command could not find commit `{commit}`. Make sure it "
            "exists on `main` or pass the full SHA."
        )
        raise SystemExit(0)

    full_sha = rev_parse.stdout.strip()
    short_sha = full_sha[:12]
    safe_release = release_branch.replace("/", "-")
    work_branch = f"automation/cherry-pick-{safe_release}-{short_sha}-{RUN_ID}"

    run(["git", "checkout", "-B", work_branch, f"origin/{release_branch}"])
    cherry_pick = run(["git", "cherry-pick", "-x", full_sha], check=False)
    if cherry_pick.returncode != 0:
        run(["git", "cherry-pick", "--abort"], check=False)
        detail = (cherry_pick.stderr or cherry_pick.stdout or "unknown conflict").strip()
        comment(
            "Cherry-pick needs manual resolution.\n\n"
            f"- Commit: `{short_sha}`\n"
            f"- Target: `{release_branch}`\n\n"
            "```text\n"
            f"{detail[-3500:]}\n"
            "```"
        )
        raise SystemExit(0)

    run(["git", "push", "--set-upstream", "origin", work_branch])

    title = f"chore(release): cherry-pick {short_sha} to {release_branch}"
    body_lines = [
        f"Cherry-picks `{full_sha}` to `{release_branch}`.",
        "",
        f"Refs #{ISSUE_NUMBER}",
    ]
    if parent:
        body_lines.append(f"Release tracking: #{parent['number']}")
    body_lines.extend(
        [
            "",
            "Created by `/cherry-pick`.",
        ]
    )
    pr_create = run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            REPO,
            "--base",
            release_branch,
            "--head",
            work_branch,
            "--title",
            title,
            "--body",
            "\n".join(body_lines),
        ],
        check=False,
    )
    if pr_create.returncode != 0:
        existing = run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                REPO,
                "--head",
                work_branch,
                "--json",
                "url",
                "--jq",
                ".[0].url",
            ],
            check=False,
        )
        pr_url = existing.stdout.strip()
        if not pr_url:
            print(pr_create.stderr, file=sys.stderr)
            raise SystemExit(pr_create.returncode)
    else:
        pr_url = pr_create.stdout.strip()

    comment(
        "Cherry-pick PR created.\n\n"
        f"- Commit: `{short_sha}`\n"
        f"- Target: `{release_branch}`\n"
        f"- PR: {pr_url}"
    )
    return pr_url


def main() -> None:
    try:
        ensure_maintainer()
        commit, release_branch, parent = resolve_inputs()
    except PermissionError as exc:
        comment(str(exc))
        return
    except ValueError as exc:
        comment(f"Cherry-pick command could not run: {exc}")
        return

    create_cherry_pick_pr(commit, release_branch, parent)


if __name__ == "__main__":
    main()

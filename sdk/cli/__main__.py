"""CLI entrypoint: ``python -m sdk.cli`` (run from the desktop assistant repo root)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sdk.file_transactions import atomic_write_text
from sdk.path_contract import (
    project_root,
    resolve_managed_project_path,
    resolve_project_output_path,
    resolve_project_read_path,
    safe_path_component,
    validate_exact_path_text,
)

from sdk.cli.registry_ops import (
    dump_registry_json,
    exact_registry_entry,
    load_registry_json,
    merge_registry_entry,
    normalize_repo_slug,
    run_git_commit,
)
from sdk.cli.scaffold import package_to_class_suffix, validate_package_name, write_plugin_project


def _resolve_create_root(value: str) -> Path:
    raw = validate_exact_path_text(
        value,
        field="plugin scaffold root",
        allow_dot_root=True,
    )
    if raw == ".":
        return project_root()
    return resolve_project_output_path(raw, root=project_root())


def _cmd_create(ns: argparse.Namespace) -> int:
    package = validate_package_name(ns.package)
    plugin_id = ns.plugin_id or f"com.example.{package}"
    safe_path_component(plugin_id, field="plugin id")
    display_name = (ns.display_name or "").strip() or package.replace("_", " ").title()
    root = _resolve_create_root(ns.root)
    dest = write_plugin_project(
        root=root,
        package=package,
        plugin_id=plugin_id,
        display_name=display_name,
        include_settings_ui=not ns.minimal,
    )
    suffix = package_to_class_suffix(package)
    entry = f"plugins.{package}.plugin:{suffix}Plugin"
    print(f"Created plugin package at {dest}")
    print(f"Suggested manifest entry: {entry}")
    print("Next: add YAML row under data/config/plugins.yaml, restart the app, then publish via:")
    print(f'  python -m sdk.cli registry-snippet --name "{display_name}" ...')
    return 0


def _cmd_registry_snippet(ns: argparse.Namespace) -> int:
    repo = normalize_repo_slug(ns.repo)
    row = {
        "name": ns.name.strip(),
        "author": ns.author.strip(),
        "repo": repo,
        "description": ns.description.strip(),
        "entry": exact_registry_entry(ns.entry),
    }
    text = json.dumps(row, ensure_ascii=False, indent=2)
    print(text)
    print(
        "\n# Paste into Shinsekai-Plugin-Registry/plugins.json (array element), "
        "or use:\n#   python -m sdk.cli registry-append --registry /path/to/clone ...",
        file=sys.stderr,
    )
    return 0


def _cmd_registry_append(ns: argparse.Namespace) -> int:
    registry_root = resolve_project_read_path(ns.registry, root=project_root())
    if not registry_root.is_dir():
        print(f"Missing {registry_root}", file=sys.stderr)
        return 2
    json_path = resolve_managed_project_path(
        "plugins.json" if ns.file is None else ns.file,
        root=registry_root,
    )
    if not json_path.is_file():
        print(f"Missing {json_path}", file=sys.stderr)
        return 2

    rows = load_registry_json(json_path)
    merged = merge_registry_entry(
        rows,
        name=ns.name,
        author=ns.author,
        repo=ns.repo,
        description=ns.description,
        entry=ns.entry,
        replace=ns.replace,
    )
    body = dump_registry_json(merged)

    if ns.dry_run:
        print(body)
        print("\n(dry-run: plugins.json not modified)", file=sys.stderr)
        return 0

    atomic_write_text(json_path, body)
    print(f"Wrote {json_path}")

    if ns.commit:
        msg = ns.message.strip() or f"registry: add {ns.name.strip()}"
        run_git_commit(
            registry_root,
            msg,
            file_path=json_path.relative_to(registry_root).as_posix(),
        )
        print(f"Committed in {registry_root}: {msg!r}")
        print("Push your branch and open a PR against Shinsekai-Plugin-Registry.", file=sys.stderr)
    else:
        print(
            f"Suggested:\n  cd {registry_root}\n"
            "  git add plugins.json\n"
            f'  git commit -m "registry: add {ns.name.strip()}"\n'
            "  git push",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Easy AI Desktop Assistant — SDK developer helpers "
            "(run inside the assistant repository clone)."
        )
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("create", help="Scaffold plugins/<package>/ (PluginBase + README)")
    p_c.add_argument("package", help="Snake_case package name, e.g. my_screen_tool")
    p_c.add_argument(
        "--root",
        default=".",
        help="Assistant repo root (default: active Shinsekai project root)",
    )
    p_c.add_argument("--plugin-id", dest="plugin_id", default="", help="Stable id, default com.example.<package>")
    p_c.add_argument("--display-name", dest="display_name", default="", help="Settings nav label / human title")
    p_c.add_argument(
        "--minimal",
        action="store_true",
        help="Empty initialize() without a settings UI stub",
    )
    p_c.set_defaults(func=_cmd_create)

    p_s = sub.add_parser(
        "registry-snippet",
        help="Print one plugins.json object for manual paste or review",
    )
    p_s.add_argument("--name", required=True)
    p_s.add_argument("--author", required=True)
    p_s.add_argument("--repo", required=True, help="GitHub slug owner/repo")
    p_s.add_argument("--description", required=True)
    p_s.add_argument(
        "--entry",
        required=True,
        help="Import path for YAML/registry, often pkg.plugin:Class (without plugins. prefix)",
    )
    p_s.set_defaults(func=_cmd_registry_snippet)

    p_a = sub.add_parser(
        "registry-append",
        help="Merge an entry into a local Shinsekai-Plugin-Registry clone (plugins.json)",
    )
    p_a.add_argument(
        "--registry",
        required=True,
        help="Path to local git clone of Shinsekai-Plugin-Registry",
    )
    p_a.add_argument(
        "--file",
        default=None,
        help="Alternate plugins.json path (default: <registry>/plugins.json)",
    )
    p_a.add_argument("--name", required=True)
    p_a.add_argument("--author", required=True)
    p_a.add_argument("--repo", required=True)
    p_a.add_argument("--description", required=True)
    p_a.add_argument("--entry", required=True)
    p_a.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing row with the same owner/repo",
    )
    p_a.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merged JSON only; do not write files",
    )
    p_a.add_argument(
        "--commit",
        action="store_true",
        help="Run git add plugins.json && git commit after writing",
    )
    p_a.add_argument(
        "--message",
        default="",
        help="Commit message when --commit is set",
    )
    p_a.set_defaults(func=_cmd_registry_append)

    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())

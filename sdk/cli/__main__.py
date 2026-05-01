"""CLI entrypoint: ``python -m sdk.cli`` (run from the desktop assistant repo root)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sdk.cli.registry_ops import (
    dump_registry_json,
    load_registry_json,
    merge_registry_entry,
    run_git_commit,
)
from sdk.cli.scaffold import package_to_class_suffix, validate_package_name, write_plugin_project


def _cmd_create(ns: argparse.Namespace) -> int:
    package = validate_package_name(ns.package)
    plugin_id = (ns.plugin_id or "").strip() or f"com.example.{package}"
    display_name = (ns.display_name or "").strip() or package.replace("_", " ").title()
    root = Path(ns.root).resolve()
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
    row = {
        "name": ns.name.strip(),
        "author": ns.author.strip(),
        "repo": ns.repo.strip().strip("/"),
        "description": ns.description.strip(),
        "entry": ns.entry.strip(),
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
    registry_root = Path(ns.registry).resolve()
    json_path = Path(ns.file).resolve() if ns.file else registry_root / "plugins.json"
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

    json_path.write_text(body, encoding="utf-8")
    print(f"Wrote {json_path}")

    if ns.commit:
        msg = ns.message.strip() or f"registry: add {ns.name.strip()}"
        run_git_commit(registry_root, msg)
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
        type=Path,
        default=Path("."),
        help="Assistant repo root (default: current directory)",
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
        type=Path,
        help="Path to local git clone of Shinsekai-Plugin-Registry",
    )
    p_a.add_argument(
        "--file",
        type=Path,
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

from __future__ import annotations

import ast
import configparser
import json
import re
from pathlib import Path
from typing import Any


METADATA_NAMES = ("plugin.json", "shinsekai.plugin.json")
README_NAMES = ("README.md", "README.MD", "readme.md", "README.txt")
LOGO_PATTERNS = ("logo.png", "logo.jpg", "logo.jpeg", "icon.png", "icon.jpg", "icon.jpeg")
TAG_SPLIT_RE = re.compile(r"[,\s\uFF0C\u3001]+")


def scan_local_plugin(path: str | Path) -> dict[str, Any]:
    root = Path(path or ".").expanduser().resolve()
    warnings: list[str] = []
    if not root.exists():
        raise FileNotFoundError(f"plugin path not found: {root}")
    if not root.is_dir():
        raise ValueError("plugin path must be a directory")

    readme = find_first(root, README_NAMES)
    metadata_path = find_first(root, METADATA_NAMES)
    metadata = read_plugin_metadata(metadata_path, warnings) if metadata_path else {}
    package_dir = infer_package_dir(root)
    entry = infer_entry(root, package_dir)
    repo = read_git_remote(root)
    title, desc = read_readme_title_desc(readme) if readme else ("", "")

    if not any(root.iterdir()):
        warnings.append("Plugin directory is empty.")
    if not entry:
        warnings.append("Could not preview plugin entry. Registry CI will infer it from the submitted repository.")
    if not repo:
        warnings.append("Could not infer GitHub repository from git remote.")

    display_name = (
        metadata_string(metadata, "display_name")
        or metadata_string(metadata, "name")
        or title
        or root.name.replace("_", " ").replace("-", " ").strip().title()
    )
    metadata_repo = metadata_string(metadata, "repo")
    repo = metadata_repo or repo
    metadata_logo = metadata_string(metadata, "logo")
    logo = resolve_metadata_logo(root, metadata_logo) if metadata_logo else find_logo(root)
    requirements = root / "requirements.txt"

    return {
        "author": metadata_string(metadata, "author") or infer_author_from_repo(repo),
        "desc": metadata_string(metadata, "desc") or metadata_string(metadata, "description") or desc,
        "display_name": display_name,
        "entry": metadata_string(metadata, "entry") or entry,
        "logo": logo.as_posix() if logo else "",
        "package_dir": package_dir.as_posix() if package_dir else "",
        "path": root.as_posix(),
        "repo": repo,
        "requirements": requirements.as_posix() if requirements.exists() else "",
        "lowest_shinsekai_version": metadata_string(metadata, "lowest_shinsekai_version")
        or metadata_string(metadata, "shinsekai_version"),
        "social_link": metadata_string(metadata, "social_link") or infer_social_link(repo),
        "tags": metadata_list(metadata, "tags"),
        "warnings": warnings,
    }


def find_first(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def read_plugin_metadata(path: Path, warnings: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        warnings.append(f"Could not parse {path.name}: {exc.msg}.")
        return {}
    if not isinstance(payload, dict):
        warnings.append(f"{path.name} must contain a JSON object.")
        return {}
    return payload


def metadata_string(metadata: dict[str, Any], field: str) -> str:
    value = metadata.get(field)
    return value.strip() if isinstance(value, str) else ""


def metadata_list(metadata: dict[str, Any], field: str) -> list[str]:
    value = metadata.get(field)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [part.strip() for part in TAG_SPLIT_RE.split(value) if part.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def resolve_metadata_logo(root: Path, value: str) -> Path | None:
    raw = value.strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve() if candidate.exists() and candidate.is_file() else None


def find_logo(root: Path) -> Path | None:
    for name in LOGO_PATTERNS:
        candidate = root / name
        if candidate.exists() and candidate.is_file():
            return candidate
    assets = root / "assets"
    if assets.exists() and assets.is_dir():
        for name in LOGO_PATTERNS:
            candidate = assets / name
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def read_readme_title_desc(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    title = ""
    desc = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not title and line.startswith("#"):
            title = line.lstrip("#").strip()
            continue
        if title and not desc and not line.startswith("#"):
            desc = line
            break
    return title, desc


def infer_package_dir(root: Path) -> Path | None:
    if (root / "plugin.py").exists():
        return root
    children = [child for child in root.iterdir() if child.is_dir() and (child / "plugin.py").exists()]
    if len(children) == 1:
        return children[0]
    for child in sorted(children, key=lambda item: item.name):
        if child.name not in {".venv", "__pycache__", "node_modules"}:
            return child
    return None


def infer_entry(root: Path, package_dir: Path | None) -> str:
    if package_dir is None:
        return ""
    plugin_file = package_dir / "plugin.py"
    if not plugin_file.exists():
        return ""
    class_name = first_plugin_class(plugin_file) or "Plugin"
    if package_dir == root:
        module = f"plugins.{python_identifier(root.name)}.plugin"
    else:
        module = f"plugins.{python_identifier(package_dir.name)}.plugin"
    return f"{module}:{class_name}"


def first_plugin_class(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return ""
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    for name in classes:
        if name.lower().endswith("plugin"):
            return name
    return classes[0] if classes else ""


def python_identifier(value: str) -> str:
    cleaned = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not cleaned:
        return "plugin"
    if cleaned[0].isdigit():
        cleaned = f"plugin_{cleaned}"
    return cleaned


def read_git_remote(root: Path) -> str:
    current = root
    for directory in (root, *root.parents):
        config_path = directory / ".git" / "config"
        if config_path.exists():
            current = directory
            break
    else:
        return ""

    parser = configparser.ConfigParser()
    parser.read(current / ".git" / "config", encoding="utf-8")
    for section in ("remote \"origin\"", "remote \"upstream\""):
        if parser.has_option(section, "url"):
            return normalize_remote_url(parser.get(section, "url"))
    return ""


def normalize_remote_url(value: str) -> str:
    raw = value.strip()
    ssh_match = re.fullmatch(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?", raw)
    if ssh_match:
        return f"https://github.com/{ssh_match.group(1)}/{ssh_match.group(2)}"
    https_match = re.fullmatch(r"https://github\.com/([^/]+)/(.+?)(?:\.git)?/?", raw)
    if https_match:
        return f"https://github.com/{https_match.group(1)}/{https_match.group(2)}"
    return raw


def infer_author_from_repo(repo: str) -> str:
    match = re.fullmatch(r"https://github\.com/([^/]+)/[^/]+", repo.strip())
    return match.group(1) if match else ""


def infer_social_link(repo: str) -> str:
    author = infer_author_from_repo(repo)
    return f"https://github.com/{author}" if author else ""

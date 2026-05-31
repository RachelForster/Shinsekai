from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a Shinsekai Python runtime.")
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--platform", required=True, choices=("linux", "macos", "windows"))
    parser.add_argument("--arch", required=True, choices=("x64", "arm64"))
    parser.add_argument("--archive-type", required=True, choices=("tar-gz", "zip"))
    parser.add_argument("--official-base-url", default="")
    parser.add_argument("--china-base-url", default="")
    args = parser.parse_args()

    runtime_dir = Path(args.runtime_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    manifest_path = Path(args.manifest).resolve()
    if not runtime_dir.is_dir():
        raise SystemExit(f"runtime dir does not exist: {runtime_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name(args.platform, args.arch, args.archive_type)
    if args.archive_type == "zip":
        write_zip(runtime_dir, archive_path)
    else:
        write_tar_gz(runtime_dir, archive_path)

    digest = sha256_file(archive_path)
    update_manifest(
        manifest_path,
        platform=args.platform,
        arch=args.arch,
        archive_type=args.archive_type,
        sha256=digest,
        filename=archive_path.name,
        official_base_url=args.official_base_url.strip(),
        china_base_url=args.china_base_url.strip(),
    )
    print(f"Packaged {archive_path}")
    print(f"sha256 {digest}")


def archive_name(platform: str, arch: str, archive_type: str) -> str:
    suffix = ".zip" if archive_type == "zip" else ".tar.gz"
    return f"shinsekai-runtime-{platform}-{arch}{suffix}"


def write_tar_gz(runtime_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in runtime_paths(runtime_dir):
            archive.add(path, arcname=path.relative_to(runtime_dir), recursive=False)


def write_zip(runtime_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in runtime_paths(runtime_dir):
            archive.write(path, arcname=path.relative_to(runtime_dir))


def runtime_paths(runtime_dir: Path):
    for path in sorted(runtime_dir.rglob("*")):
        if should_skip(path):
            continue
        yield path


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if "__pycache__" in parts or ".cache" in parts:
        return True
    name = path.name
    return name == ".DS_Store" or name == "get-pip.py" or name.endswith((".pyc", ".pyo"))


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def update_manifest(
    manifest_path: Path,
    *,
    platform: str,
    arch: str,
    archive_type: str,
    sha256: str,
    filename: str,
    official_base_url: str,
    china_base_url: str,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = {
        "platform": platform,
        "arch": arch,
        "archive_type": archive_type,
        "sha256": sha256,
    }
    if official_base_url:
        target["official_url"] = f"{official_base_url.rstrip('/')}/{filename}"
    if china_base_url:
        target["china_url"] = f"{china_base_url.rstrip('/')}/{filename}"

    targets = [
        item
        for item in manifest.get("targets", [])
        if not (item.get("platform") == platform and item.get("arch") == arch)
    ]
    targets.append(target)
    manifest["targets"] = targets
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

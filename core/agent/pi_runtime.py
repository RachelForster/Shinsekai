"""Pinned official Pi runtime installation, using the shared archive downloader."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from filelock import FileLock

from core.downloads import DownloadInterrupted, download_archive

PI_VERSION = "1.0.4"
PI_RELEASE = "https://github.com/earendil-works/pi/releases/download/v" + PI_VERSION
# Published SHA256SUMS for v1.0.4; upgrades require changing this pinned manifest.
PI_ARCHIVES = {
    "darwin-arm64": (
        "pi-darwin-arm64.tar.gz",
        "717dcd38a03849e919f9dec9daa96f5ca102e15ea33d804e5db57b1d47e513bc",
    ),
    "darwin-x64": (
        "pi-darwin-x64.tar.gz",
        "665022918678542dd7c87fe7b0da70d2a3dcd926bc6ff4cc712308f2ca313358",
    ),
    "linux-x64": (
        "pi-linux-x64.tar.gz",
        "284c45dd28cf975a13cff6af34741dd0a0cdca6634e8bdfc0083ae7d452e86d6",
    ),
    "linux-arm64": (
        "pi-linux-arm64.tar.gz",
        "6a6bc66a6ac2750bd7ccd7f2109090463f564d447feefb10a5965f6b6aed2211",
    ),
    "windows-x64": (
        "pi-windows-x64.zip",
        "6bdbfb7bac252eea36a0095e4b741c9d5784d5ba99146e2d76e9246dee409b58",
    ),
    "windows-arm64": (
        "pi-windows-arm64.zip",
        "ca8a2f2687d2097d3f93ead151e943315a262cf499abe6635c09e293cced164d",
    ),
}


def pi_platform(system: str | None = None, machine: str | None = None) -> str:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "x64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    key = f"{system}-{arch}"
    if key not in PI_ARCHIVES:
        raise ValueError(f"Pi has no supported official runtime for {system}/{machine}")
    return key


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _target(root: Path, name: str) -> Path:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or any(part in ("..", "/") or ":" in part for part in parts):
        raise ValueError("Unsafe Pi archive path")
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Pi archive path escapes its installation")
    return path


@dataclass(frozen=True)
class PiRuntime:
    executable: Path
    version: str = PI_VERSION


class PiRuntimeManager:
    def __init__(self, root: str | Path, *, platform_key: str | None = None) -> None:
        self.root = Path(root).resolve()
        self.platform_key = platform_key or pi_platform()
        if self.platform_key not in PI_ARCHIVES:
            raise ValueError("Unsupported Pi platform")
        self.name, self.sha256 = PI_ARCHIVES[self.platform_key]
        self.installed = self.root / f"{PI_VERSION}-{self.platform_key}"

    def inspect(self) -> PiRuntime | None:
        try:
            marker = json.loads(
                (self.installed / "installed.json").read_text(encoding="utf-8")
            )
            if (marker["version"], marker["platform"], marker["archiveSha256"]) != (
                PI_VERSION,
                self.platform_key,
                self.sha256,
            ):
                return None
            if not marker["files"]:
                return None
            for name, expected in marker["files"].items():
                path = _target(self.installed, name)
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or file_digest(path) != expected
                ):
                    return None
            executable = _target(self.installed, marker["executable"])
            if marker["executable"] not in marker["files"]:
                return None
            if os.name != "nt" and not os.access(executable, os.X_OK):
                return None
            return PiRuntime(executable)
        except (OSError, ValueError, AttributeError, KeyError, TypeError):
            return None

    def ensure(
        self,
        *,
        update_task: Callable[..., None] = lambda **_: None,
        is_interrupted: Callable[[], bool] = lambda: False,
    ) -> PiRuntime:
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.root / "install.lock"), timeout=0):
            update_task(phase="verify", progress=0.01, message="Checking Pi runtime")
            cached = self.inspect()
            if is_interrupted():
                raise DownloadInterrupted()
            if cached:
                return cached
            archive = self.root / "downloads" / self.name
            if not archive.is_file() or file_digest(archive) != self.sha256:
                update_task(
                    phase="download",
                    progress=0.02,
                    message="Downloading official Pi runtime",
                )
                download_archive(
                    PI_RELEASE + "/" + self.name,
                    archive,
                    {"User-Agent": "Shinsekai-Pi-Runtime"},
                    expected_sha256=self.sha256,
                    is_interrupted=is_interrupted,
                    on_progress=lambda value: update_task(
                        phase="download",
                        progress=value / 100,
                        message="Downloading official Pi runtime",
                    ),
                    timeout=(15, 5),
                )
            stage = Path(tempfile.mkdtemp(prefix="install-", dir=self.root))
            backup = None
            try:
                update_task(
                    phase="extract", progress=0.75, message="Installing Pi runtime"
                )
                self._extract(archive, stage, is_interrupted)
                binary_name = (
                    "pi.exe" if self.platform_key.startswith("windows-") else "pi"
                )
                binaries = [path for path in stage.rglob(binary_name) if path.is_file()]
                if len(binaries) != 1:
                    raise ValueError(
                        "Official Pi archive must contain exactly one executable"
                    )
                executable = binaries[0]
                if os.name != "nt":
                    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
                files = {
                    p.relative_to(stage).as_posix(): file_digest(p)
                    for p in stage.rglob("*")
                    if p.is_file()
                }
                (stage / "installed.json").write_text(
                    json.dumps(
                        {
                            "version": PI_VERSION,
                            "platform": self.platform_key,
                            "archiveSha256": self.sha256,
                            "executable": executable.relative_to(stage).as_posix(),
                            "files": files,
                        }
                    ),
                    encoding="utf-8",
                )
                if is_interrupted():
                    raise DownloadInterrupted()
                if self.installed.exists():
                    backup = self.root / (stage.name + "-previous")
                    self.installed.rename(backup)
                try:
                    stage.rename(self.installed)
                except BaseException:
                    if backup:
                        backup.rename(self.installed)
                        backup = None
                    raise
                update_task(phase="ready", progress=1.0, message="Pi runtime ready")
                return PiRuntime(self.installed / executable.relative_to(stage))
            finally:
                for path in (stage, backup):
                    if path and path.is_dir() and path.resolve().parent == self.root:
                        shutil.rmtree(path)

    def _extract(
        self, archive: Path, root: Path, interrupted: Callable[[], bool]
    ) -> None:
        total, count = 0, 0

        def copy(name, size, stream):
            nonlocal total, count
            total, count = total + size, count + 1
            if total > 2 * 1024**3 or count > 20000:
                raise ValueError("Pi archive exceeds installation limits")
            target = _target(root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                while chunk := stream.read(128 * 1024):
                    if interrupted():
                        raise DownloadInterrupted()
                    output.write(chunk)
            return target

        if self.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    _target(root, member.filename)
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Pi archive links are not supported")
                    if not member.is_dir():
                        with source.open(member) as stream:
                            copy(member.filename, member.file_size, stream)
        else:
            with tarfile.open(archive, "r:gz") as source:
                for member in source:
                    _target(root, member.name)
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("Pi archive contains an unsupported entry")
                    with source.extractfile(member) as stream:
                        target = copy(member.name, member.size, stream)
                        target.chmod(member.mode & 0o777)

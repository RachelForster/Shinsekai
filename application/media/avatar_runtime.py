"""User-installed format runtimes, outside read-only application/frontend assets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from filelock import FileLock

from application.media.resource_paths import MediaResourcePaths
from core.media.asset_import import PendingAssetBatch, recover_asset_batches
from core.media.avatar.registry import adapter_for
from sdk.path_utils import safe_child_path
from sdk.file_io import durable_mkdir, durable_rename, sync_directory


class AvatarRuntimeService:
    def __init__(self, project_root: Path, *, file_access_roots=()):
        self.paths = MediaResourcePaths(project_root, file_access_roots=file_access_roots)

    def _runtime(self, format_id: str):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", format_id):
            raise ValueError("Invalid avatar format")
        installer = adapter_for(format_id).runtime_installer
        if installer is None:
            raise ValueError("This format does not require a user-installed runtime")
        root = safe_child_path(self.paths.project_root, f"data/runtime/avatars/{format_id}")
        return installer, root

    @staticmethod
    def _manifest(root: Path) -> dict:
        try:
            manifest = root / "current.json"
            if manifest.stat().st_size > 8192:
                return {}
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if (isinstance(value, dict) and isinstance(value.get("files"), dict)
                    and isinstance(value.get("version"), str)
                    and re.fullmatch(r"\.batch-[0-9a-f]{32}", str(value.get("batch", "")))):
                return value
        except (OSError, ValueError):
            pass
        return {}

    def status(self, format_id: str) -> dict:
        installer, root = self._runtime(format_id)
        recover_asset_batches(root, lambda batch: self._manifest(root).get("batch") == batch.name)
        try:
            for name in installer.filenames:
                self.file(format_id, name)
            installed = True
        except (FileNotFoundError, ValueError, PermissionError, OSError):
            installed = False
        return {"version": installer.version, "installed": installed, "download_url": installer.download_url,
                "license_urls": list(installer.license_urls)}

    def _source(self, body: dict) -> Path:
        if body.get("accepted_license") is not True:
            raise ValueError("Read and accept the SDK licenses before importing")
        return self.paths.input_file(body.get("source_path"), field="SDK ZIP")

    def prepare(self, format_id: str, body: dict) -> dict:
        installer, _ = self._runtime(format_id)
        return installer.prepare(self._source(body))

    def install(self, format_id: str, body: dict) -> dict:
        installer, root = self._runtime(format_id)
        files = installer.files(self._source(body), body.get("compiled"))
        if set(files) != set(installer.filenames):
            raise ValueError("Incomplete runtime output")
        durable_mkdir(root)
        with FileLock(str(root / ".install.lock")):
            recover_asset_batches(root, lambda batch: self._manifest(root).get("batch") == batch.name)
            if self.status(format_id)["installed"]:
                return self.status(format_id)  # The pinned runtime is immutable; no replacement required.
            with PendingAssetBatch(root) as batch:
                for name, content in files.items():
                    with safe_child_path(batch.path, name).open("xb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                # Persist the files' directory entries before a manifest can
                # reference them. The subsequent durable rename also syncs root.
                sync_directory(batch.path)
                manifest = {"batch": batch.path.name, "version": installer.version,
                            "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
                temporary = root / f".current-{uuid.uuid4().hex}.json"
                try:
                    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                        json.dump(manifest, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                    durable_rename(temporary, root / "current.json", replace=True)
                    batch.commit()
                except Exception:
                    # POSIX rename may succeed before directory fsync fails.
                    # Report failure, but never delete files a visible manifest
                    # already references; retain the marker for recovery.
                    if self._manifest(root).get("batch") == batch.path.name:
                        batch.preserve()
                    raise
                finally:
                    temporary.unlink(missing_ok=True)
        return self.status(format_id)

    def file(self, format_id: str, filename: str) -> Path:
        installer, root = self._runtime(format_id)
        if filename not in installer.filenames:
            raise PermissionError("Unapproved runtime file")
        manifest = self._manifest(root)
        if not manifest or manifest.get("version") != installer.version:
            raise FileNotFoundError("Avatar runtime is not installed")
        target = safe_child_path(root, f"{manifest['batch']}/{filename}")
        if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
            raise FileNotFoundError("Avatar runtime is incomplete")
        if hashlib.sha256(target.read_bytes()).hexdigest() != manifest.get("files", {}).get(filename):
            raise ValueError("Avatar runtime file failed integrity verification")
        return target

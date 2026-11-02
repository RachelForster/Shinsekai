"""Disk-backed recovery for a story deletion spanning multiple history directories."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile
from zipfile import ZipFile

from sdk.file_io import durable_mkdir, durable_rename, sync_directory


def restore_deletion(backup: Path) -> None:
    """Restore removed files; keep the archive until every restore has succeeded.

    This also provides explicit recovery after an interrupted application. Only
    use archives created by this application: the manifest contains original,
    absolute paths, including registered histories outside the history root.
    """
    errors = []
    with ZipFile(backup) as archive:
        for item in json.loads(archive.read("manifest.json")):
            path = Path(item["path"])
            temporary = None
            try:
                # Deletion only unlinks files; surviving files need no rewrite.
                if path.exists() or path.is_symlink():
                    continue
                durable_mkdir(path.parent)
                if "symlink" in item:
                    path.symlink_to(item["symlink"])
                    sync_directory(path.parent)
                    continue
                with archive.open(item["entry"]) as source, tempfile.NamedTemporaryFile(
                    dir=path.parent, delete=False
                ) as target:
                    temporary = Path(target.name)
                    shutil.copyfileobj(source, target)
                    target.flush()
                    os.fsync(target.fileno())
                temporary.chmod(item["mode"])
                os.utime(temporary, ns=(item["atimeNs"], item["mtimeNs"]))
                durable_rename(temporary, path)
            except OSError as error:
                errors.append(error)
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as error:
                        errors.append(error)
    if errors:
        raise OSError(f"Could not restore {len(errors)} file(s) from {backup}") from errors[0]


@contextmanager
def recoverable_deletion(files: Iterable[Path], recovery_dir: Path) -> Iterator[None]:
    """Back up every existing target before unlinking any; roll back on failure."""
    durable_mkdir(recovery_dir)
    with tempfile.NamedTemporaryFile(
        prefix="story-delete-", suffix=".zip", dir=recovery_dir, delete=False
    ) as target:
        backup = Path(target.name)
        try:
            with ZipFile(target, "w") as archive:
                manifest = []
                for path in dict.fromkeys(Path(file).absolute() for file in files):
                    try:
                        info = path.lstat()
                    except FileNotFoundError:
                        continue
                    item = {
                        "path": str(path), "entry": str(len(manifest)), "mode": info.st_mode,
                        "atimeNs": info.st_atime_ns, "mtimeNs": info.st_mtime_ns,
                    }
                    if path.is_symlink():
                        item["symlink"] = os.readlink(path)
                    else:
                        archive.write(path, item["entry"])
                    manifest.append(item)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            target.flush()
            os.fsync(target.fileno())
            sync_directory(recovery_dir)
        except BaseException:
            target.close()
            backup.unlink(missing_ok=True)
            raise
    try:
        yield
        # One unlink commits the deletion; never partially purge recovery files.
        backup.unlink()
    except BaseException:
        try:
            restore_deletion(backup)
        except Exception as error:
            raise RuntimeError(f"删除失败，自动恢复未完成；完整恢复副本保留在 {backup}") from error
        try:
            backup.unlink()
        except OSError:
            pass  # Files are restored; keep the recovery copy if it is locked.
        raise

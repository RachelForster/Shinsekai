from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import sdk.file_transactions as file_transactions
from sdk.file_transactions import (
    atomic_binary_writer,
    atomic_write_bytes,
    atomic_write_text,
    clear_directory_without_links,
    copy_directory_without_links,
    copy_file_exclusive,
    copy_file_transactionally,
    create_private_temporary_directory,
    inspect_portable_directory_tree,
    open_binary_read_without_links,
    open_binary_write_exclusive_without_links,
    open_text_append_without_links,
    private_temporary_directory,
    read_bytes_snapshot_without_links,
    read_bytes_without_links,
    read_text_without_links,
    remove_directory_without_links,
    remove_empty_directory_without_links,
    remove_file_without_links,
    remove_link_without_following,
    rename_path_without_overwrite,
    replace_file_transactionally,
    portable_name_key,
    replace_directory_transactionally,
    snapshot_directory_entries_without_links,
    write_bytes_exclusive,
)


def test_atomic_write_text_preserves_previous_file_when_publish_fails(tmp_path, monkeypatch):
    target = tmp_path / "template.txt"
    target.write_text("old", encoding="utf-8")
    real_rename = rename_path_without_overwrite

    def fail_replace(source, destination, *, expected_identity=None):
        if destination == target and Path(source).name.endswith(".tmp"):
            raise OSError("publish failed")
        return real_rename(
            source,
            destination,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "sdk.file_transactions.rename_path_without_overwrite",
        fail_replace,
    )

    with pytest.raises(OSError, match="publish failed"):
        atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".template.txt.*.tmp")) == []


def test_atomic_write_and_remove_support_maximum_length_filename(tmp_path):
    target = tmp_path / (("界" * 83) + "ab.txt")

    atomic_write_text(target, "first")
    atomic_write_text(target, "second")

    assert target.read_text(encoding="utf-8") == "second"
    assert len(target.name.encode("utf-8")) == 255
    remove_file_without_links(target, expected_identity=target.lstat())
    assert not target.exists()


def test_private_temporary_directory_fits_an_oversized_prefix(tmp_path):
    temporary, identity = create_private_temporary_directory(
        prefix="界" * 100,
        directory=tmp_path,
    )
    try:
        assert len(temporary.name.encode("utf-8")) <= 255
        assert temporary.is_dir()
    finally:
        remove_directory_without_links(
            temporary,
            expected_identity=identity,
        )


def test_rename_path_without_overwrite_publishes_exact_source_identity(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("complete", encoding="utf-8")
    source_identity = source.lstat()

    published = rename_path_without_overwrite(
        source,
        destination,
        expected_identity=source_identity,
    )

    assert published == destination
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "complete"
    assert os.path.samestat(source_identity, destination.lstat())


def test_rename_path_without_overwrite_preserves_occupied_destination(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")
    destination.write_text("peer", encoding="utf-8")

    with pytest.raises(FileExistsError):
        rename_path_without_overwrite(source, destination)

    assert source.read_text(encoding="utf-8") == "source"
    assert destination.read_text(encoding="utf-8") == "peer"


def test_rename_path_without_overwrite_rejects_stale_source_identity(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("original", encoding="utf-8")
    stale_identity = source.lstat()
    source.replace(tmp_path / "preserved.txt")
    source.write_text("replacement", encoding="utf-8")

    with pytest.raises(PermissionError, match="identity changed"):
        rename_path_without_overwrite(
            source,
            destination,
            expected_identity=stale_identity,
        )

    assert source.read_text(encoding="utf-8") == "replacement"
    assert not destination.exists()


def test_rename_path_without_overwrite_rejects_stale_expected_parent(tmp_path):
    managed = tmp_path / "managed"
    preserved_parent = tmp_path / "preserved-managed"
    managed.mkdir()
    expected_parent_identity = managed.lstat()
    managed.rename(preserved_parent)
    managed.mkdir()
    source = managed / "source.txt"
    destination = managed / "destination.txt"
    source.write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="source parent identity changed"):
        rename_path_without_overwrite(
            source,
            destination,
            expected_source_parent_identity=expected_parent_identity,
            expected_destination_parent_identity=expected_parent_identity,
        )

    assert source.read_text(encoding="utf-8") == "peer"
    assert not destination.exists()


def test_rename_path_without_overwrite_binds_parent_before_native_call(
    tmp_path,
    monkeypatch,
):
    managed = tmp_path / "managed"
    preserved_parent = tmp_path / "preserved-managed"
    managed.mkdir()
    source = managed / "source.bin"
    destination = managed / "destination.bin"
    source.write_bytes(b"original")
    real_native_rename = file_transactions._native_rename_without_overwrite

    def replace_parent_then_rename(source_path, destination_path, **identities):
        managed.rename(preserved_parent)
        managed.mkdir()
        source.write_bytes(b"peer")
        return real_native_rename(
            source_path,
            destination_path,
            **identities,
        )

    monkeypatch.setattr(
        file_transactions,
        "_native_rename_without_overwrite",
        replace_parent_then_rename,
    )

    with pytest.raises(PermissionError, match="parent identity changed"):
        rename_path_without_overwrite(source, destination)

    assert source.read_bytes() == b"peer"
    assert not destination.exists()
    assert (preserved_parent / "source.bin").read_bytes() == b"original"


def test_rename_path_without_overwrite_rejects_parent_replaced_after_publication(
    tmp_path,
    monkeypatch,
):
    managed = tmp_path / "managed"
    preserved_parent = tmp_path / "preserved-managed"
    managed.mkdir()
    source = managed / "source.bin"
    destination = managed / "destination.bin"
    source.write_bytes(b"original")
    real_native_rename = file_transactions._native_rename_without_overwrite

    def rename_then_replace_parent(source_path, destination_path, **identities):
        real_native_rename(
            source_path,
            destination_path,
            **identities,
        )
        managed.rename(preserved_parent)
        managed.mkdir()
        destination.write_bytes(b"peer")

    monkeypatch.setattr(
        file_transactions,
        "_native_rename_without_overwrite",
        rename_then_replace_parent,
    )

    with pytest.raises(PermissionError, match="parent identity changed"):
        rename_path_without_overwrite(source, destination)

    assert destination.read_bytes() == b"peer"
    assert (preserved_parent / "destination.bin").read_bytes() == b"original"


def test_atomic_write_text_rejects_lexical_alias_before_write(tmp_path):
    alias = f"{tmp_path.as_posix()}/./template.txt"

    with pytest.raises(ValueError, match="lexical path aliases"):
        atomic_write_text(alias, "new")

    assert not (tmp_path / "template.txt").exists()


def test_atomic_write_text_rejects_relative_targets_instead_of_using_cwd(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        atomic_write_text("template.txt", "new")

    assert not (tmp_path / "template.txt").exists()


def test_atomic_write_text_rejects_filesystem_root(tmp_path):
    root = tmp_path.anchor

    with pytest.raises(PermissionError, match="filesystem root"):
        atomic_write_text(root, "new")


def test_atomic_write_text_rejects_intermediate_symlink(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link component"):
        atomic_write_text(alias / "template.txt", "new")

    assert not (external / "template.txt").exists()


def test_link_free_read_helpers_preserve_exact_regular_file_identity(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("内容", encoding="utf-8")

    assert read_text_without_links(source) == "内容"
    assert read_bytes_without_links(source) == "内容".encode()


def test_link_free_read_helpers_reject_leaf_symlink(tmp_path):
    source = tmp_path / "source.txt"
    alias = tmp_path / "alias.txt"
    source.write_text("secret", encoding="utf-8")
    try:
        alias.symlink_to(source)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        read_bytes_without_links(alias)


def test_link_free_reader_rejects_a_replacement_expected_file(tmp_path):
    source = tmp_path / "source.txt"
    preserved = tmp_path / "preserved.txt"
    source.write_text("original", encoding="utf-8")
    expected_identity = source.lstat()
    source.rename(preserved)
    source.write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="identity changed"):
        with open_binary_read_without_links(
            source,
            expected_identity=expected_identity,
        ):
            pass

    assert source.read_text(encoding="utf-8") == "peer"
    assert preserved.read_text(encoding="utf-8") == "original"


def test_link_free_reader_rejects_in_place_change_after_expected_snapshot(
    tmp_path,
):
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    expected_identity = source.lstat()
    source.write_text("replacement-is-longer", encoding="utf-8")

    with pytest.raises(PermissionError, match="identity changed"):
        with open_binary_read_without_links(
            source,
            expected_identity=expected_identity,
        ):
            pass


def test_link_free_reader_rejects_a_replacement_expected_parent(tmp_path):
    parent = tmp_path / "inputs"
    preserved_parent = tmp_path / "preserved-inputs"
    parent.mkdir()
    source = parent / "source.txt"
    source.write_text("original", encoding="utf-8")
    expected_parent_identity = parent.lstat()
    parent.rename(preserved_parent)
    parent.mkdir()
    source.write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="parent identity changed"):
        with open_binary_read_without_links(
            source,
            expected_parent_identity=expected_parent_identity,
        ):
            pass

    assert source.read_text(encoding="utf-8") == "peer"
    assert (preserved_parent / "source.txt").read_text(encoding="utf-8") == "original"


def test_snapshot_read_rejects_in_place_mutation(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"original")
    real_open = file_transactions.open_binary_read_without_links

    @contextmanager
    def mutate_after_read(*args, **kwargs):
        with real_open(*args, **kwargs) as handle:
            class MutatingReader:
                def fileno(self):
                    return handle.fileno()

                def read(self):
                    payload = handle.read()
                    source.write_bytes(b"replacement-is-longer")
                    return payload

            yield MutatingReader()

    monkeypatch.setattr(
        file_transactions,
        "open_binary_read_without_links",
        mutate_after_read,
    )

    with pytest.raises(PermissionError, match="changed while it was being read"):
        read_bytes_snapshot_without_links(source)

    assert source.read_bytes() == b"replacement-is-longer"


def test_directory_snapshot_rejects_replaced_directory(tmp_path, monkeypatch):
    directory = tmp_path / "catalog"
    preserved = tmp_path / "catalog-preserved"
    directory.mkdir()
    (directory / "original.txt").write_text("original", encoding="utf-8")
    real_scandir = file_transactions.os.scandir

    @contextmanager
    def replace_after_scan(path):
        with real_scandir(path) as scanner:
            yield scanner
        directory.rename(preserved)
        directory.mkdir()
        (directory / "peer.txt").write_text("peer", encoding="utf-8")

    monkeypatch.setattr(file_transactions.os, "scandir", replace_after_scan)

    with pytest.raises(PermissionError, match="identity changed"):
        snapshot_directory_entries_without_links(directory)

    assert (directory / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved / "original.txt").read_text(encoding="utf-8") == "original"


def test_portable_tree_inventory_never_restats_scanned_names_by_public_path(
    tmp_path,
    monkeypatch,
):
    if (
        os.scandir not in os.supports_fd
        or os.stat not in os.supports_dir_fd
    ):
        pytest.skip("descriptor-relative directory scans are unavailable")

    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "root.txt").write_text("root", encoding="utf-8")
    (nested / "child.txt").write_text("child", encoding="utf-8")
    real_scandir = file_transactions.os.scandir

    class EntryWithoutPublicRestat:
        def __init__(self, entry):
            self._entry = entry
            self.name = entry.name
            self.path = entry.path

        def stat(self, *, follow_symlinks=False):
            raise AssertionError(
                "DirEntry.stat() would resolve the public directory name again"
            )

    @contextmanager
    def scan_without_public_restat(path):
        with real_scandir(path) as scanner:
            yield (
                EntryWithoutPublicRestat(entry)
                for entry in scanner
            )

    monkeypatch.setattr(
        file_transactions.os,
        "scandir",
        scan_without_public_restat,
    )
    monkeypatch.setattr(
        file_transactions.os,
        "supports_fd",
        {*os.supports_fd, scan_without_public_restat},
    )

    directories, files = inspect_portable_directory_tree(source)

    assert directories == [Path("nested")]
    assert set(files) == {Path("root.txt"), Path("nested/child.txt")}


def test_exclusive_write_helper_creates_one_exact_regular_file(tmp_path):
    target = tmp_path / "managed.bin"

    with open_binary_write_exclusive_without_links(target) as output:
        output.write(b"content")

    assert target.read_bytes() == b"content"
    with pytest.raises(FileExistsError):
        open_binary_write_exclusive_without_links(target)


def test_exclusive_write_helper_rejects_a_linked_parent(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        open_binary_write_exclusive_without_links(alias / "managed.bin")

    assert not (external / "managed.bin").exists()


def test_exclusive_write_helper_rejects_replaced_expected_parent(tmp_path):
    parent = tmp_path / "managed"
    parent.mkdir()
    expected_parent_identity = parent.lstat()
    preserved_parent = tmp_path / "preserved-managed"
    parent.rename(preserved_parent)
    parent.mkdir()

    with pytest.raises(PermissionError, match="parent identity changed"):
        open_binary_write_exclusive_without_links(
            parent / "managed.bin",
            expected_parent_identity=expected_parent_identity,
        )

    assert list(parent.iterdir()) == []
    assert list(preserved_parent.iterdir()) == []


def test_atomic_write_text_revalidates_parent_after_creating_it(tmp_path, monkeypatch):
    parent = tmp_path / "managed"
    external = tmp_path / "external"
    external.mkdir()
    original_mkdir = Path.mkdir
    swapped = False

    def create_then_swap(path, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(path, *args, **kwargs)
        if path == parent and not swapped:
            swapped = True
            path.rmdir()
            try:
                path.symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError):
                pytest.skip("symbolic links are unavailable")
        return result

    monkeypatch.setattr(Path, "mkdir", create_then_swap)

    with pytest.raises(PermissionError, match="symbolic link component"):
        atomic_write_text(parent / "template.txt", "new")

    assert not (external / "template.txt").exists()


def test_atomic_write_text_rejects_replaced_expected_parent(tmp_path):
    parent = tmp_path / "managed"
    preserved = tmp_path / "managed-preserved"
    parent.mkdir()
    expected_parent = parent.lstat()
    rename_path_without_overwrite(
        parent,
        preserved,
        expected_identity=expected_parent,
    )
    parent.mkdir()
    peer = parent / "template.txt"
    peer.write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="parent identity changed"):
        atomic_write_text(
            peer,
            "stale",
            expected_parent_identity=expected_parent,
        )

    assert peer.read_text(encoding="utf-8") == "peer"


def test_atomic_write_bytes_rejects_leaf_symlink(tmp_path):
    external = tmp_path / "external.bin"
    target = tmp_path / "managed.bin"
    external.write_bytes(b"private")
    try:
        target.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        atomic_write_bytes(target, b"replacement")

    assert external.read_bytes() == b"private"


def test_atomic_binary_writer_preserves_previous_file_when_stream_fails(tmp_path):
    target = tmp_path / "download.bin"
    target.write_bytes(b"complete")

    with pytest.raises(RuntimeError, match="stream failed"):
        with atomic_binary_writer(target) as handle:
            handle.write(b"partial")
            raise RuntimeError("stream failed")

    assert target.read_bytes() == b"complete"
    assert list(tmp_path.glob(".download.bin.*.tmp")) == []


def test_replace_file_transactionally_publishes_complete_sibling(tmp_path):
    target = tmp_path / "cache.wav"
    staging = tmp_path / ".cache.wav.encoder-part"
    target.write_bytes(b"old")
    staging.write_bytes(b"complete")

    published = replace_file_transactionally(staging, target)

    assert published == target
    assert target.read_bytes() == b"complete"
    assert not staging.exists()


def test_replace_file_transactionally_preserves_target_on_publish_failure(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "archive.zip"
    staging = tmp_path / ".archive.zip.writer-part"
    target.write_bytes(b"old")
    staging.write_bytes(b"complete")
    real_rename = rename_path_without_overwrite

    def fail_replace(source, destination, *, expected_identity=None):
        if source == staging and destination == target:
            raise OSError("publish failed")
        return real_rename(
            source,
            destination,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "sdk.file_transactions.rename_path_without_overwrite",
        fail_replace,
    )

    with pytest.raises(OSError, match="publish failed"):
        replace_file_transactionally(staging, target)

    assert target.read_bytes() == b"old"
    assert staging.read_bytes() == b"complete"
    assert not list(tmp_path.glob(".archive.zip.backup-*"))


def test_replace_file_transactionally_rejects_stale_expected_staging_identity(
    tmp_path,
):
    target = tmp_path / "archive.zip"
    staging = tmp_path / ".archive.zip.writer-part"
    preserved = tmp_path / "preserved.zip"
    target.write_bytes(b"old")
    staging.write_bytes(b"complete")
    staging_identity = staging.lstat()
    staging.rename(preserved)
    staging.write_bytes(b"replacement")

    with pytest.raises(PermissionError, match="staging file identity changed"):
        replace_file_transactionally(
            staging,
            target,
            expected_staging_identity=staging_identity,
        )

    assert target.read_bytes() == b"old"
    assert staging.read_bytes() == b"replacement"
    assert preserved.read_bytes() == b"complete"


def test_replace_file_transactionally_preserves_changed_expected_destination(
    tmp_path,
):
    target = tmp_path / "archive.zip"
    staging = tmp_path / ".archive.zip.writer-part"
    preserved = tmp_path / "preserved.zip"
    target.write_bytes(b"old")
    target_identity = target.lstat()
    staging.write_bytes(b"complete")
    target.rename(preserved)
    target.write_bytes(b"peer")

    with pytest.raises(PermissionError, match="destination file identity changed"):
        replace_file_transactionally(
            staging,
            target,
            expected_destination_identity=target_identity,
        )

    assert target.read_bytes() == b"peer"
    assert staging.read_bytes() == b"complete"
    assert preserved.read_bytes() == b"old"


def test_replace_file_transactionally_preserves_destination_that_was_expected_absent(
    tmp_path,
):
    target = tmp_path / "archive.zip"
    staging = tmp_path / ".archive.zip.writer-part"
    staging.write_bytes(b"complete")
    target.write_bytes(b"peer")

    with pytest.raises(FileExistsError, match="appeared before publication"):
        replace_file_transactionally(
            staging,
            target,
            expected_destination_identity=None,
        )

    assert target.read_bytes() == b"peer"
    assert staging.read_bytes() == b"complete"


def test_replace_file_transactionally_rejects_destination_symlink(tmp_path):
    external = tmp_path / "external.wav"
    target = tmp_path / "cache.wav"
    staging = tmp_path / ".cache.wav.encoder-part"
    external.write_bytes(b"private")
    staging.write_bytes(b"complete")
    try:
        target.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        replace_file_transactionally(staging, target)

    assert target.is_symlink()
    assert external.read_bytes() == b"private"
    assert staging.read_bytes() == b"complete"


def test_replace_file_transactionally_requires_same_parent(tmp_path):
    staging = tmp_path / "temporary" / "cache.wav"
    target = tmp_path / "managed" / "cache.wav"
    staging.parent.mkdir()
    target.parent.mkdir()
    staging.write_bytes(b"complete")

    with pytest.raises(ValueError, match="share a parent"):
        replace_file_transactionally(staging, target)

    assert staging.read_bytes() == b"complete"
    assert not target.exists()


def test_replace_file_transactionally_rejects_stale_expected_parent(tmp_path):
    parent = tmp_path / "publication"
    preserved = tmp_path / "publication-preserved"
    parent.mkdir()
    expected_parent = parent.lstat()
    rename_path_without_overwrite(
        parent,
        preserved,
        expected_identity=expected_parent,
    )
    parent.mkdir()
    staging = parent / "staging.bin"
    target = parent / "target.bin"
    staging.write_bytes(b"stale")
    target.write_bytes(b"peer")

    with pytest.raises(PermissionError, match="parent identity changed"):
        replace_file_transactionally(
            staging,
            target,
            expected_parent_identity=expected_parent,
        )

    assert staging.read_bytes() == b"stale"
    assert target.read_bytes() == b"peer"


def test_replace_file_transactionally_rejects_replaced_staging_identity(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "archive.zip"
    staging = tmp_path / ".archive.zip.writer-part"
    replacement = tmp_path / "replacement.zip"
    preserved_original = tmp_path / "original-staging.zip"
    target.write_bytes(b"old")
    staging.write_bytes(b"complete")
    replacement.write_bytes(b"replacement")
    real_fsync = os.fsync
    replaced = False

    def replace_after_sync(descriptor):
        nonlocal replaced
        real_fsync(descriptor)
        if not replaced:
            replaced = True
            staging.rename(preserved_original)
            replacement.rename(staging)

    monkeypatch.setattr("sdk.file_transactions.os.fsync", replace_after_sync)

    with pytest.raises(PermissionError, match="identity changed"):
        replace_file_transactionally(staging, target)

    assert target.read_bytes() == b"old"
    assert staging.read_bytes() == b"replacement"
    assert preserved_original.read_bytes() == b"complete"


def test_copy_file_transactionally_replaces_only_after_complete_copy(tmp_path):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"complete")
    target.write_bytes(b"old")

    published = copy_file_transactionally(source, target)

    assert published == target
    assert target.read_bytes() == b"complete"
    assert list(tmp_path.glob(".target.bin.*.copy")) == []


def test_copy_file_transactionally_preserves_target_when_copy_fails(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"complete")
    target.write_bytes(b"old")

    def fail_copy(input_file, output_file):
        output_file.write(input_file.read(2))
        raise OSError("copy failed")

    monkeypatch.setattr("sdk.file_transactions.shutil.copyfileobj", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        copy_file_transactionally(source, target)

    assert target.read_bytes() == b"old"
    assert list(tmp_path.glob(".target.bin.*.copy")) == []


def test_copy_file_transactionally_rejects_in_place_source_mutation(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"complete")
    target.write_bytes(b"old")
    real_copy = file_transactions.shutil.copyfileobj

    def copy_then_mutate_source(input_file, output_file):
        real_copy(input_file, output_file)
        source.write_bytes(b"changed")

    monkeypatch.setattr(
        "sdk.file_transactions.shutil.copyfileobj",
        copy_then_mutate_source,
    )

    with pytest.raises(PermissionError, match="changed while it was being copied"):
        copy_file_transactionally(source, target)

    assert source.read_bytes() == b"changed"
    assert target.read_bytes() == b"old"
    assert list(tmp_path.glob(".target.bin.*.copy")) == []


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="descriptor chmod is unavailable")
def test_copy_file_transactionally_never_changes_replacement_staging_metadata(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    preserved_staging = tmp_path / "preserved-staging.bin"
    source.write_bytes(b"complete")
    source.chmod(0o755)
    target.write_bytes(b"old")
    real_copy = file_transactions.shutil.copyfileobj
    replacement_path: Path | None = None

    def replace_staging_after_copy(input_file, output_file):
        nonlocal replacement_path
        real_copy(input_file, output_file)
        replacement_path = Path(output_file.name)
        replacement_path.rename(preserved_staging)
        replacement_path.write_bytes(b"peer")
        replacement_path.chmod(0o600)

    monkeypatch.setattr(
        "sdk.file_transactions.shutil.copyfileobj",
        replace_staging_after_copy,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        copy_file_transactionally(source, target)

    assert replacement_path is not None
    assert replacement_path.read_bytes() == b"peer"
    assert stat.S_IMODE(replacement_path.stat().st_mode) == 0o600
    assert preserved_staging.read_bytes() == b"complete"
    assert stat.S_IMODE(preserved_staging.stat().st_mode) == 0o755
    assert target.read_bytes() == b"old"


def test_copy_file_transactionally_rejects_source_symlink(tmp_path):
    external = tmp_path / "external.bin"
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    external.write_bytes(b"private")
    try:
        source.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        copy_file_transactionally(source, target)

    assert not target.exists()


def test_copy_file_transactionally_rejects_stale_source_and_destination_parent(
    tmp_path,
):
    source_parent = tmp_path / "source"
    destination_parent = tmp_path / "destination"
    preserved_source_parent = tmp_path / "source-preserved"
    preserved_destination_parent = tmp_path / "destination-preserved"
    source_parent.mkdir()
    destination_parent.mkdir()
    source = source_parent / "payload.bin"
    source.write_bytes(b"original")
    source_identity = source.lstat()
    source_parent_identity = source_parent.lstat()
    destination_parent_identity = destination_parent.lstat()

    source_parent.rename(preserved_source_parent)
    source_parent.mkdir()
    peer_source = source_parent / "payload.bin"
    peer_source.write_bytes(b"peer")
    with pytest.raises(PermissionError, match="source file parent identity changed"):
        copy_file_transactionally(
            peer_source,
            destination_parent / "payload.bin",
            expected_source_identity=source_identity,
            expected_source_parent_identity=source_parent_identity,
            expected_destination_parent_identity=destination_parent_identity,
        )
    assert peer_source.read_bytes() == b"peer"
    assert not (destination_parent / "payload.bin").exists()

    destination_parent.rename(preserved_destination_parent)
    destination_parent.mkdir()
    peer_destination = destination_parent / "payload.bin"
    peer_destination.write_bytes(b"destination peer")
    with pytest.raises(PermissionError, match="destination parent identity changed"):
        copy_file_transactionally(
            preserved_source_parent / "payload.bin",
            peer_destination,
            expected_destination_parent_identity=destination_parent_identity,
        )
    assert peer_destination.read_bytes() == b"destination peer"
    assert (preserved_source_parent / "payload.bin").read_bytes() == b"original"


def test_open_text_append_without_links_rejects_leaf_symlink(tmp_path):
    external = tmp_path / "external.log"
    target = tmp_path / "managed.log"
    external.write_text("private", encoding="utf-8")
    try:
        target.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises((OSError, PermissionError)):
        open_text_append_without_links(target)

    assert external.read_text(encoding="utf-8") == "private"


def test_open_text_append_without_links_appends_to_regular_file(tmp_path):
    target = tmp_path / "logs/runtime.log"

    with open_text_append_without_links(target) as handle:
        handle.write("first\n")
    with open_text_append_without_links(target) as handle:
        handle.write("second\n")

    assert target.read_text(encoding="utf-8") == "first\nsecond\n"


def test_open_text_append_without_links_rejects_replaced_parent_identity(
    tmp_path,
):
    parent = tmp_path / "logs"
    preserved = tmp_path / "logs-preserved"
    parent.mkdir()
    expected_parent_identity = parent.lstat()
    parent.rename(preserved)
    parent.mkdir()
    peer = parent / "runtime.log"
    peer.write_text("peer\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="parent identity changed"):
        open_text_append_without_links(
            peer,
            expected_parent_identity=expected_parent_identity,
        )

    assert peer.read_text(encoding="utf-8") == "peer\n"
    assert list(preserved.iterdir()) == []


def test_private_temporary_directory_removes_its_owned_tree(tmp_path):
    with private_temporary_directory(
        prefix="owned-temp-",
        directory=tmp_path,
    ) as temporary:
        identity = temporary.lstat()
        (temporary / "nested").mkdir()
        (temporary / "nested" / "payload.txt").write_text("payload", encoding="utf-8")

    assert not temporary.exists()
    assert stat.S_ISDIR(identity.st_mode)


def test_private_temporary_directory_preserves_a_replacement_identity(tmp_path):
    with private_temporary_directory(
        prefix="owned-temp-",
        directory=tmp_path,
    ) as temporary:
        original = temporary.with_name(f"{temporary.name}-original")
        temporary.rename(original)
        temporary.mkdir()
        (temporary / "peer.txt").write_text("peer", encoding="utf-8")

    assert (temporary / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert original.is_dir()


def test_clear_directory_without_links_preserves_root_identity(tmp_path):
    root = tmp_path / "owned"
    root.mkdir()
    identity = root.lstat()
    (root / "nested").mkdir()
    (root / "nested" / "payload.txt").write_text("nested", encoding="utf-8")
    (root / "payload.txt").write_text("file", encoding="utf-8")

    clear_directory_without_links(root, expected_identity=identity)

    assert root.is_dir()
    assert os.path.samestat(identity, root.lstat())
    assert list(root.iterdir()) == []


def test_clear_directory_without_links_preserves_replacement_root(tmp_path):
    root = tmp_path / "owned"
    root.mkdir()
    identity = root.lstat()
    preserved = tmp_path / "preserved"
    root.rename(preserved)
    root.mkdir()
    (root / "peer.txt").write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="identity changed"):
        clear_directory_without_links(root, expected_identity=identity)

    assert (root / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert preserved.is_dir()


def test_create_private_temporary_directory_rejects_relative_parent():
    with pytest.raises(ValueError, match="absolute"):
        create_private_temporary_directory(
            prefix="owned-temp-",
            directory=Path("relative"),
        )


def test_copy_file_exclusive_uses_distinct_names_under_concurrency(tmp_path):
    source = tmp_path / "incoming/image.png"
    source.parent.mkdir()
    source.write_bytes(b"image")
    destination = tmp_path / "managed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(
            executor.map(
                lambda _index: copy_file_exclusive(
                    source,
                    destination,
                    "Image.png",
                ),
                range(2),
            )
        )

    assert {path.name for path in paths} == {"Image.png", "Image_1.png"}
    assert all(path.read_bytes() == b"image" for path in paths)


def test_copy_file_exclusive_avoids_case_only_collision(tmp_path):
    source = tmp_path / "incoming/image.png"
    source.parent.mkdir()
    source.write_bytes(b"new")
    destination = tmp_path / "managed"
    destination.mkdir()
    (destination / "IMAGE.PNG").write_bytes(b"old")

    copied = copy_file_exclusive(source, destination, "image.png")

    assert copied.name == "image_1.png"
    assert (destination / "IMAGE.PNG").read_bytes() == b"old"
    assert copied.read_bytes() == b"new"


def test_copy_file_exclusive_rejects_source_symlink_without_partial_output(tmp_path):
    source = tmp_path / "incoming/image.png"
    external = tmp_path / "external.png"
    destination = tmp_path / "managed"
    source.parent.mkdir()
    external.write_bytes(b"private")
    try:
        source.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        copy_file_exclusive(source, destination, "image.png")

    assert not destination.exists()


def test_write_bytes_exclusive_preserves_duplicate_uploads(tmp_path):
    first = write_bytes_exclusive(tmp_path, "memory.json", b"first")
    second = write_bytes_exclusive(tmp_path, "memory.json", b"second")

    assert first.name == "memory.json"
    assert second.name == "memory_1.json"
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_write_bytes_exclusive_fits_collision_suffix_within_byte_limit(tmp_path):
    requested_name = ("界" * 83) + "ab.png"

    first = write_bytes_exclusive(tmp_path, requested_name, b"first")
    second = write_bytes_exclusive(tmp_path, requested_name, b"second")

    assert first.name == requested_name
    assert second.name == ("界" * 83) + "_1.png"
    assert len(second.name.encode("utf-8")) == 255
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_write_bytes_exclusive_rejects_parent_replaced_during_write(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "managed"
    destination.mkdir()
    preserved_destination = tmp_path / "preserved-managed"
    real_fsync = file_transactions.os.fsync
    replaced = False

    def fsync_then_replace(descriptor):
        nonlocal replaced
        real_fsync(descriptor)
        if not replaced:
            replaced = True
            destination.rename(preserved_destination)
            destination.mkdir()
            (destination / "memory.json").write_bytes(b"peer")

    monkeypatch.setattr(file_transactions.os, "fsync", fsync_then_replace)

    with pytest.raises(PermissionError, match="identity changed"):
        write_bytes_exclusive(destination, "memory.json", b"original")

    assert (destination / "memory.json").read_bytes() == b"peer"
    assert (preserved_destination / "memory.json").read_bytes() == b"original"


def test_exclusive_write_revalidates_destination_after_creating_it(tmp_path, monkeypatch):
    destination = tmp_path / "managed"
    external = tmp_path / "external"
    external.mkdir()
    original_mkdir = Path.mkdir
    swapped = False

    def create_then_swap(path, *args, **kwargs):
        nonlocal swapped
        result = original_mkdir(path, *args, **kwargs)
        if path == destination and not swapped:
            swapped = True
            path.rmdir()
            try:
                path.symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError):
                pytest.skip("symbolic links are unavailable")
        return result

    monkeypatch.setattr(Path, "mkdir", create_then_swap)

    with pytest.raises(PermissionError, match="symbolic link component"):
        write_bytes_exclusive(destination, "memory.json", b"new")

    assert not (external / "memory.json").exists()


def test_write_bytes_exclusive_serializes_portable_name_collisions(tmp_path):
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_bytes_exclusive, tmp_path, "Image.png", b"upper"),
            executor.submit(write_bytes_exclusive, tmp_path, "image.png", b"lower"),
        ]
        paths = [future.result() for future in futures]

    assert len({portable_name_key(path.name) for path in paths}) == 2
    assert {path.read_bytes() for path in paths} == {b"upper", b"lower"}


def test_copy_directory_without_links_rejects_nested_symlink(tmp_path):
    source = tmp_path / "source"
    external = tmp_path / "external.txt"
    destination = tmp_path / "destination"
    source.mkdir()
    external.write_text("private", encoding="utf-8")
    try:
        (source / "linked.txt").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        copy_directory_without_links(source, destination)

    assert not destination.exists()


def test_copy_directory_without_links_rejects_windows_reparse_entry_metadata(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    junction = source / "junction"
    destination = tmp_path / "destination"
    real_scandir = os.scandir

    class FakeEntry:
        name = junction.name
        path = str(junction)

        @staticmethod
        def stat(*, follow_symlinks=False):
            assert follow_symlinks is False
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x00000400,
                ),
            )

    class FakeScanner:
        def __enter__(self):
            return iter([FakeEntry()])

        def __exit__(self, *_args):
            return False

    def fake_scandir(path):
        if path == source:
            return FakeScanner()
        return real_scandir(path)

    monkeypatch.setattr("sdk.file_transactions.os.scandir", fake_scandir)
    monkeypatch.setattr(file_transactions.os, "supports_fd", set())

    with pytest.raises(PermissionError, match="reparse point"):
        copy_directory_without_links(source, destination)

    assert not destination.exists()


def test_copy_directory_without_links_rejects_portable_name_collision(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "Image.png").write_bytes(b"upper")
    (source / "image.png").write_bytes(b"lower")

    with pytest.raises(FileExistsError, match="portable filename collision"):
        copy_directory_without_links(source, destination)

    assert not destination.exists()


def test_copy_directory_without_links_rejects_destination_alias_before_copy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "item.txt").write_text("content", encoding="utf-8")
    destination_alias = f"{tmp_path.as_posix()}/nested/../destination"

    with pytest.raises(ValueError, match="lexical path aliases"):
        copy_directory_without_links(source, destination_alias)

    assert not (tmp_path / "destination").exists()


def test_copy_directory_without_links_rejects_stale_expected_source_identity(
    tmp_path,
):
    source = tmp_path / "source"
    preserved = tmp_path / "preserved-source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "original.txt").write_text("original", encoding="utf-8")
    source_identity = source.lstat()
    source.rename(preserved)
    source.mkdir()
    (source / "replacement.txt").write_text("replacement", encoding="utf-8")

    with pytest.raises(PermissionError, match="source directory identity changed"):
        copy_directory_without_links(
            source,
            destination,
            expected_source_identity=source_identity,
        )

    assert not destination.exists()
    assert (source / "replacement.txt").read_text(encoding="utf-8") == "replacement"
    assert (preserved / "original.txt").read_text(encoding="utf-8") == "original"


def test_copy_directory_without_links_rejects_file_replaced_after_inventory(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    preserved = tmp_path / "preserved.txt"
    source.mkdir()
    source_file = source / "payload.txt"
    source_file.write_text("original", encoding="utf-8")
    real_inventory = file_transactions._inspect_portable_directory_tree_with_metadata
    inspected = False

    def inspect_then_replace(path):
        nonlocal inspected
        result = real_inventory(path)
        if Path(path) == source and not inspected:
            inspected = True
            source_file.rename(preserved)
            source_file.write_text("replacement", encoding="utf-8")
        return result

    monkeypatch.setattr(
        file_transactions,
        "_inspect_portable_directory_tree_with_metadata",
        inspect_then_replace,
    )

    with pytest.raises(PermissionError, match="file identity changed"):
        copy_directory_without_links(source, destination)

    assert not destination.exists()
    assert source_file.read_text(encoding="utf-8") == "replacement"
    assert preserved.read_text(encoding="utf-8") == "original"


def test_copy_directory_without_links_preserves_replaced_destination_root(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    preserved = tmp_path / "preserved-destination"
    source.mkdir()
    (source / "payload.txt").write_text("original", encoding="utf-8")
    real_copy = file_transactions.shutil.copyfileobj
    replaced = False

    def replace_destination_during_copy(input_file, output_file):
        nonlocal replaced
        if not replaced:
            replaced = True
            destination.rename(preserved)
            destination.mkdir()
            (destination / "peer.txt").write_text("peer", encoding="utf-8")
        return real_copy(input_file, output_file)

    monkeypatch.setattr(
        file_transactions.shutil,
        "copyfileobj",
        replace_destination_during_copy,
    )

    with pytest.raises((FileNotFoundError, PermissionError)):
        copy_directory_without_links(source, destination)

    assert (destination / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved / "payload.txt").read_text(encoding="utf-8") == "original"


def test_remove_file_without_links_removes_exact_file(tmp_path):
    target = tmp_path / "managed.json"
    target.write_text("content", encoding="utf-8")

    remove_file_without_links(target)

    assert not target.exists()
    assert not list(tmp_path.glob(".managed.json.delete-*"))


def test_remove_file_without_links_rejects_leaf_symlink(tmp_path):
    target = tmp_path / "managed.json"
    external = tmp_path / "external.json"
    external.write_text("keep", encoding="utf-8")
    try:
        target.symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        remove_file_without_links(target)

    assert target.is_symlink()
    assert external.read_text(encoding="utf-8") == "keep"


def test_remove_file_without_links_restores_a_concurrent_replacement(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "managed.json"
    peer = tmp_path / "peer.json"
    preserved_original = tmp_path / "original.json"
    target.write_text("original", encoding="utf-8")
    peer.write_text("peer", encoding="utf-8")
    real_rename = rename_path_without_overwrite
    replaced = False

    def replace_before_rename(source, destination, *, expected_identity=None):
        nonlocal replaced
        if source == target and not replaced:
            replaced = True
            real_rename(target, preserved_original)
            real_rename(peer, target)
        return real_rename(
            source,
            destination,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "sdk.file_transactions.rename_path_without_overwrite",
        replace_before_rename,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        remove_file_without_links(target)

    assert target.read_text(encoding="utf-8") == "peer"
    assert preserved_original.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".managed.json.delete-*"))


def test_remove_file_without_links_honors_expected_identity(tmp_path):
    target = tmp_path / "managed.json"
    replacement = tmp_path / "replacement.json"
    target.write_text("original", encoding="utf-8")
    expected = target.lstat()
    target.rename(tmp_path / "preserved.json")
    replacement.write_text("replacement", encoding="utf-8")
    replacement.rename(target)

    with pytest.raises(PermissionError, match="identity changed"):
        remove_file_without_links(target, expected_identity=expected)

    assert target.read_text(encoding="utf-8") == "replacement"


def test_remove_file_without_links_rejects_replaced_expected_parent(tmp_path):
    parent = tmp_path / "managed"
    preserved_parent = tmp_path / "managed-preserved"
    parent.mkdir()
    target = parent / "probe"
    target.write_text("original", encoding="utf-8")
    target_identity = target.lstat()
    parent_identity = parent.lstat()
    parent.rename(preserved_parent)
    parent.mkdir()
    peer = parent / "probe"
    peer.write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="parent identity changed"):
        remove_file_without_links(
            peer,
            expected_identity=target_identity,
            expected_parent_identity=parent_identity,
        )

    assert peer.read_text(encoding="utf-8") == "peer"
    assert (preserved_parent / "probe").read_text(encoding="utf-8") == "original"


def test_remove_link_without_following_removes_only_the_link(tmp_path):
    target = tmp_path / "managed-link"
    external = tmp_path / "external.txt"
    external.write_text("keep", encoding="utf-8")
    try:
        target.symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    remove_link_without_following(target, expected_identity=target.lstat())

    assert not os.path.lexists(target)
    assert external.read_text(encoding="utf-8") == "keep"


def test_remove_empty_directory_without_links_rejects_nonempty_directory(tmp_path):
    target = tmp_path / "managed"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(OSError):
        remove_empty_directory_without_links(
            target,
            expected_identity=target.lstat(),
        )

    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".managed.delete-*"))


def test_remove_directory_without_links_removes_exact_tree(tmp_path):
    target = tmp_path / "managed"
    target.mkdir()
    (target / "item.txt").write_text("content", encoding="utf-8")

    remove_directory_without_links(target)

    assert not target.exists()
    assert not list(tmp_path.glob(".managed.delete-*"))


def test_remove_directory_without_links_rejects_linked_parent(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    (external / "managed").mkdir()
    marker = external / "managed" / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        remove_directory_without_links(alias / "managed")

    assert marker.read_text(encoding="utf-8") == "keep"


def test_remove_directory_without_links_does_not_follow_nested_link(tmp_path):
    target = tmp_path / "managed"
    external = tmp_path / "external"
    target.mkdir()
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        (target / "external-link").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symbolic links are unavailable")

    remove_directory_without_links(target)

    assert not target.exists()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_remove_directory_without_links_restores_name_when_cleanup_fails(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "managed"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    def fail_remove(_path):
        raise OSError("cleanup failed")

    monkeypatch.setattr("sdk.file_transactions.shutil.rmtree", fail_remove)

    with pytest.raises(OSError, match="cleanup failed"):
        remove_directory_without_links(target)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not list(tmp_path.glob(".managed.delete-*"))


def test_remove_directory_without_links_restores_a_concurrent_replacement(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "managed"
    peer = tmp_path / "peer"
    preserved_original = tmp_path / "original"
    target.mkdir()
    peer.mkdir()
    (target / "original.txt").write_text("original", encoding="utf-8")
    (peer / "peer.txt").write_text("peer", encoding="utf-8")
    real_rename = rename_path_without_overwrite
    replaced = False

    def replace_before_rename(source, destination, *, expected_identity=None):
        nonlocal replaced
        if source == target and not replaced:
            replaced = True
            real_rename(target, preserved_original)
            real_rename(peer, target)
        return real_rename(
            source,
            destination,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "sdk.file_transactions.rename_path_without_overwrite",
        replace_before_rename,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        remove_directory_without_links(target)

    assert (target / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved_original / "original.txt").read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".managed.delete-*"))


def test_replace_directory_transactionally_swaps_complete_sibling_tree(tmp_path):
    destination = tmp_path / "plugin"
    staging = tmp_path / ".plugin.install"
    destination.mkdir()
    staging.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")

    published = replace_directory_transactionally(staging, destination)

    assert published == destination
    assert not staging.exists()
    assert not (destination / "old.txt").exists()
    assert (destination / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".plugin.backup-*"))


def test_replace_directory_transactionally_restores_previous_tree_on_publish_failure(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "plugin"
    staging = tmp_path / ".plugin.install"
    destination.mkdir()
    staging.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    real_rename = rename_path_without_overwrite

    def fail_staging_publish(path, target, *, expected_identity=None):
        if path == staging and target == destination:
            raise OSError("publish failed")
        return real_rename(
            path,
            target,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "sdk.file_transactions.rename_path_without_overwrite",
        fail_staging_publish,
    )

    with pytest.raises(OSError, match="publish failed"):
        replace_directory_transactionally(staging, destination)

    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert (staging / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".plugin.backup-*"))


def test_replace_directory_transactionally_rejects_replaced_staging_identity(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "plugin"
    staging = tmp_path / ".plugin.install"
    replacement = tmp_path / "replacement"
    preserved_original = tmp_path / "original-staging"
    destination.mkdir()
    staging.mkdir()
    replacement.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    (replacement / "replacement.txt").write_text("replacement", encoding="utf-8")
    real_inspect = inspect_portable_directory_tree
    replaced = False

    def inspect_then_replace(path):
        nonlocal replaced
        result = real_inspect(path)
        if Path(path) == staging and not replaced:
            replaced = True
            staging.rename(preserved_original)
            replacement.rename(staging)
        return result

    monkeypatch.setattr(
        "sdk.file_transactions.inspect_portable_directory_tree",
        inspect_then_replace,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        replace_directory_transactionally(staging, destination)

    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert (staging / "replacement.txt").read_text(encoding="utf-8") == "replacement"
    assert (preserved_original / "new.txt").read_text(encoding="utf-8") == "new"


def test_replace_directory_transactionally_rejects_stale_expected_staging_identity(
    tmp_path,
):
    destination = tmp_path / "plugin"
    staging = tmp_path / ".plugin.install"
    preserved = tmp_path / "preserved-staging"
    destination.mkdir()
    staging.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    staging_identity = staging.lstat()
    staging.rename(preserved)
    staging.mkdir()
    (staging / "peer.txt").write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="staging directory identity changed"):
        replace_directory_transactionally(
            staging,
            destination,
            expected_staging_identity=staging_identity,
        )

    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert (staging / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved / "new.txt").read_text(encoding="utf-8") == "new"


def test_replace_directory_transactionally_preserves_changed_expected_destination(
    tmp_path,
):
    destination = tmp_path / "plugin"
    staging = tmp_path / ".plugin.install"
    preserved = tmp_path / "preserved-destination"
    destination.mkdir()
    staging.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    destination_identity = destination.lstat()
    destination.rename(preserved)
    destination.mkdir()
    (destination / "peer.txt").write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="destination directory identity changed"):
        replace_directory_transactionally(
            staging,
            destination,
            expected_destination_identity=destination_identity,
        )

    assert (destination / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (staging / "new.txt").read_text(encoding="utf-8") == "new"
    assert (preserved / "old.txt").read_text(encoding="utf-8") == "old"


def test_replace_directory_transactionally_preserves_replaced_destination(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "plugin"
    staging = tmp_path / ".plugin.install"
    replacement = tmp_path / "replacement"
    preserved_original = tmp_path / "original-destination"
    destination.mkdir()
    staging.mkdir()
    replacement.mkdir()
    (destination / "old.txt").write_text("old", encoding="utf-8")
    (staging / "new.txt").write_text("new", encoding="utf-8")
    (replacement / "peer.txt").write_text("peer", encoding="utf-8")
    real_rename = rename_path_without_overwrite
    replaced = False

    def replace_before_backup(source, target, *, expected_identity=None):
        nonlocal replaced
        if source == destination and not replaced:
            replaced = True
            real_rename(destination, preserved_original)
            real_rename(replacement, destination)
        return real_rename(
            source,
            target,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "sdk.file_transactions.rename_path_without_overwrite",
        replace_before_backup,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        replace_directory_transactionally(staging, destination)

    assert (destination / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved_original / "old.txt").read_text(encoding="utf-8") == "old"
    assert (staging / "new.txt").read_text(encoding="utf-8") == "new"


def test_replace_directory_transactionally_requires_same_parent(tmp_path):
    staging = tmp_path / "temporary" / "plugin"
    destination = tmp_path / "managed" / "plugin"
    staging.mkdir(parents=True)
    destination.parent.mkdir()

    with pytest.raises(ValueError, match="share a parent"):
        replace_directory_transactionally(staging, destination)

    assert staging.is_dir()
    assert not destination.exists()


def test_replace_directory_transactionally_rejects_stale_expected_parent(
    tmp_path,
):
    parent = tmp_path / "publication"
    preserved = tmp_path / "publication-preserved"
    parent.mkdir()
    expected_parent = parent.lstat()
    rename_path_without_overwrite(
        parent,
        preserved,
        expected_identity=expected_parent,
    )
    parent.mkdir()
    staging = parent / "staging"
    destination = parent / "destination"
    staging.mkdir()
    destination.mkdir()
    (staging / "new.txt").write_text("stale", encoding="utf-8")
    (destination / "old.txt").write_text("peer", encoding="utf-8")

    with pytest.raises(PermissionError, match="parent identity changed"):
        replace_directory_transactionally(
            staging,
            destination,
            expected_parent_identity=expected_parent,
        )

    assert (staging / "new.txt").read_text(encoding="utf-8") == "stale"
    assert (destination / "old.txt").read_text(encoding="utf-8") == "peer"

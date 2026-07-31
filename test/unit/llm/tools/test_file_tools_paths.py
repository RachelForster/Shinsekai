from __future__ import annotations

import errno
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from sdk.file_transactions import rename_path_without_overwrite
from core.media.file_operations import (
    _resolve,
    append_text_file as file_append,
    copy_file as file_copy,
    create_directory as file_mkdir,
    delete_path as file_delete,
    extract_archive as file_extract,
    inspect_path as file_info,
    list_directory as file_list_dir,
    move_path as file_move,
    open_local_path as file_open,
    read_text_file as file_read,
    search_file_content as file_search_content,
    search_files as file_search,
    write_text_file as file_write,
)


def test_file_open_rejects_symbolic_link_alias(tmp_path, monkeypatch):
    target = tmp_path / "target.txt"
    alias = tmp_path / "alias.txt"
    target.write_text("safe", encoding="utf-8")
    try:
        alias.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")
    calls = []
    monkeypatch.setattr(
        "core.media.file_operations.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = file_open(alias.as_posix())

    assert "symbolic link" in result["error"]
    assert calls == []


def test_file_delete_reports_size_after_removal(tmp_path):
    target = tmp_path / "remove.txt"
    target.write_bytes(b"1234")

    result = file_delete(target.as_posix())

    assert result == {
        "deleted": target.as_posix(),
        "type": "file",
        "size_human": "4.0B",
    }
    assert not target.exists()


@pytest.mark.parametrize(
    "raw",
    (
        "folder//file.txt",
        "./file.txt",
        "folder/../file.txt",
    ),
)
def test_file_tools_reject_relative_lexical_aliases(raw):
    with pytest.raises((PermissionError, ValueError), match="exact|escapes"):
        _resolve(raw)


@pytest.mark.parametrize("pattern", ("../*", "../../*", "**/../*", r"..\*"))
def test_file_search_patterns_cannot_escape_the_selected_directory(
    tmp_path,
    pattern,
):
    selected = tmp_path / "selected"
    selected.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private marker", encoding="utf-8")

    with pytest.raises(PermissionError, match="escapes"):
        file_search(pattern, selected.as_posix())
    with pytest.raises(PermissionError, match="escapes"):
        file_search_content(
            "private marker",
            selected.as_posix(),
            pattern,
        )


def test_file_search_does_not_return_a_link_outside_the_selected_directory(
    tmp_path,
):
    selected = tmp_path / "selected"
    selected.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private marker", encoding="utf-8")
    linked = selected / "linked.txt"
    try:
        linked.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    file_result = file_search("*.txt", selected.as_posix())
    content_result = file_search_content(
        "private marker",
        selected.as_posix(),
        "*.txt",
    )

    assert file_result["matches"] == []
    assert content_result["matches"] == []


def test_file_search_does_not_mix_a_replaced_nested_directory(
    tmp_path,
    monkeypatch,
):
    selected = tmp_path / "selected"
    nested = selected / "nested"
    preserved = selected / "nested-preserved"
    nested.mkdir(parents=True)
    (nested / "original.txt").write_text("original marker", encoding="utf-8")
    from core.media import file_operations as file_tools

    real_snapshot = file_tools.snapshot_directory_entries_without_links
    replaced = False

    def replace_nested_after_snapshot(path, **kwargs):
        nonlocal replaced
        result = real_snapshot(path, **kwargs)
        if Path(path) == nested and not replaced:
            replaced = True
            nested.rename(preserved)
            nested.mkdir()
            (nested / "peer.txt").write_text("peer marker", encoding="utf-8")
        return result

    monkeypatch.setattr(
        file_tools,
        "snapshot_directory_entries_without_links",
        replace_nested_after_snapshot,
    )

    file_result = file_search("*.txt", selected.as_posix())
    peer_preserved = tmp_path / "peer-preserved"
    nested.rename(peer_preserved)
    preserved.rename(nested)
    replaced = False
    content_result = file_search_content(
        "marker",
        selected.as_posix(),
        "*.txt",
    )

    assert file_result["matches"] == []
    assert content_result["matches"] == []
    assert (nested / "peer.txt").read_text(encoding="utf-8") == "peer marker"
    assert (
        preserved / "original.txt"
    ).read_text(encoding="utf-8") == "original marker"


def test_file_read_does_not_follow_leaf_symlink(tmp_path):
    external = tmp_path / "external.txt"
    link = tmp_path / "linked.txt"
    external.write_text("private marker", encoding="utf-8")
    try:
        link.symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    result = file_read(link.as_posix())
    info = file_info(link.as_posix())

    assert "error" in result
    assert info["type"] == "symbolic-link"
    assert "private marker" not in str(result)


def test_file_list_rejects_replaced_directory(tmp_path, monkeypatch):
    directory = tmp_path / "directory"
    preserved = tmp_path / "directory-preserved"
    directory.mkdir()
    (directory / "original.txt").write_text("original", encoding="utf-8")
    from core.media import file_operations as file_tools

    real_snapshot = file_tools.snapshot_directory_entries_without_links

    def replace_after_snapshot(*args, **kwargs):
        result = real_snapshot(*args, **kwargs)
        directory.rename(preserved)
        directory.mkdir()
        (directory / "peer.txt").write_text("peer", encoding="utf-8")
        return result

    monkeypatch.setattr(
        file_tools,
        "snapshot_directory_entries_without_links",
        replace_after_snapshot,
    )

    result = file_list_dir(directory.as_posix())

    assert "error" in result
    assert (directory / "peer.txt").read_text(encoding="utf-8") == "peer"
    assert (preserved / "original.txt").read_text(
        encoding="utf-8"
    ) == "original"


def test_file_list_default_is_home_not_process_cwd(tmp_path, monkeypatch):
    home = tmp_path / "home"
    launcher = tmp_path / "launcher"
    home.mkdir()
    launcher.mkdir()
    (home / "home.txt").write_text("home", encoding="utf-8")
    (launcher / "cwd.txt").write_text("cwd", encoding="utf-8")
    monkeypatch.chdir(launcher)
    monkeypatch.setattr(
        "core.media.file_operations.user_home_directory",
        lambda: home,
    )

    result = file_list_dir()

    assert result["path"] == home.as_posix()
    assert [item["name"] for item in result["items"]] == ["home.txt"]


def test_file_delete_rejects_absolute_lexical_alias(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_text("keep", encoding="utf-8")
    alias = f"{tmp_path.as_posix()}/./keep.txt"

    with pytest.raises(ValueError, match="lexical path aliases"):
        file_delete(alias)

    assert target.read_text(encoding="utf-8") == "keep"


def test_file_delete_removes_link_instead_of_link_target(tmp_path):
    target = tmp_path / "target.txt"
    link = tmp_path / "link.txt"
    target.write_text("keep", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    result = file_delete(link.as_posix())

    assert result["type"] == "symbolic-link"
    assert not link.exists()
    assert target.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("operation", ("write", "append", "copy"))
def test_file_writes_do_not_follow_existing_destination_link(
    tmp_path,
    operation,
):
    target = tmp_path / "target.txt"
    link = tmp_path / "link.txt"
    source = tmp_path / "source.txt"
    target.write_text("keep", encoding="utf-8")
    source.write_text("replacement", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    if operation == "write":
        result = file_write(link.as_posix(), "replacement")
    elif operation == "append":
        result = file_append(link.as_posix(), "replacement")
    else:
        result = file_copy(source.as_posix(), link.as_posix())

    assert "symbolic link" in result["error"]
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep"


def test_file_move_moves_link_identity_instead_of_target(tmp_path):
    target = tmp_path / "target.txt"
    source_link = tmp_path / "source-link.txt"
    destination = tmp_path / "moved-link.txt"
    target.write_text("keep", encoding="utf-8")
    try:
        source_link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    result = file_move(source_link.as_posix(), destination.as_posix())

    assert "error" not in result
    assert not source_link.exists()
    assert destination.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep"


def test_relative_write_target_rejects_linked_home_descendant(tmp_path, monkeypatch):
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")
    monkeypatch.setattr("core.media.file_operations.user_home_directory", lambda: tmp_path)

    with pytest.raises(PermissionError, match="symbolic link"):
        file_write("alias/escaped.txt", "blocked")

    assert not (external / "escaped.txt").exists()


@pytest.mark.parametrize(
    "operation",
    ("write", "append", "copy", "move", "extract", "mkdir"),
)
def test_mutating_file_tools_reject_absolute_intermediate_directory_link(
    tmp_path,
    operation,
):
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    source = tmp_path / "source.txt"
    archive = tmp_path / "archive.zip"
    external.mkdir()
    source.write_text("source", encoding="utf-8")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("payload.txt", "payload")
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    destination = alias / ("directory" if operation in {"extract", "mkdir"} else "file.txt")
    with pytest.raises(PermissionError, match="symbolic link"):
        if operation == "write":
            file_write(destination.as_posix(), "blocked")
        elif operation == "append":
            file_append(destination.as_posix(), "blocked")
        elif operation == "copy":
            file_copy(source.as_posix(), destination.as_posix())
        elif operation == "move":
            file_move(source.as_posix(), destination.as_posix())
        elif operation == "extract":
            file_extract(archive.as_posix(), destination.as_posix())
        else:
            file_mkdir(destination.as_posix())

    assert not (external / destination.name).exists()
    assert source.exists()


def test_file_move_treats_destination_as_exact_identity(tmp_path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination"
    source.write_text("source", encoding="utf-8")
    destination.mkdir()

    result = file_move(source.as_posix(), destination.as_posix())

    assert "Destination already exists" in result["error"]
    assert source.read_text(encoding="utf-8") == "source"
    assert not (destination / source.name).exists()


def _simulate_cross_volume_rename(monkeypatch, source: Path, destination: Path) -> None:
    real_rename = rename_path_without_overwrite

    def rename_with_cross_volume_error(
        path: Path,
        target: Path,
        *,
        expected_identity=None,
    ):
        if path == source and Path(target) == destination:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_rename(
            path,
            target,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "core.media.file_operations.rename_path_without_overwrite",
        rename_with_cross_volume_error,
    )


def test_file_move_cross_volume_file_publishes_complete_target(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.txt"
    destination_dir = tmp_path / "other-volume"
    destination = destination_dir / "destination.txt"
    source.write_text("complete", encoding="utf-8")
    destination_dir.mkdir()
    _simulate_cross_volume_rename(monkeypatch, source, destination)

    result = file_move(source.as_posix(), destination.as_posix())

    assert "error" not in result
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "complete"
    assert not list(tmp_path.glob(".*.move-source-*"))
    assert not list(destination_dir.glob(".*.move-target-*"))


def test_file_move_cross_volume_rejects_source_replaced_after_exdev(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.txt"
    preserved = tmp_path / "source-preserved.txt"
    destination_dir = tmp_path / "other-volume"
    destination = destination_dir / "destination.txt"
    source.write_text("original", encoding="utf-8")
    destination_dir.mkdir()
    real_rename = rename_path_without_overwrite
    raced = False

    def replace_then_report_exdev(path, target, *, expected_identity=None):
        nonlocal raced
        if path == source and Path(target) == destination and not raced:
            raced = True
            source.rename(preserved)
            source.write_text("peer", encoding="utf-8")
            raise OSError(errno.EXDEV, "cross-device link")
        return real_rename(
            path,
            target,
            expected_identity=expected_identity,
        )

    monkeypatch.setattr(
        "core.media.file_operations.rename_path_without_overwrite",
        replace_then_report_exdev,
    )

    result = file_move(source.as_posix(), destination.as_posix())

    assert "identity changed" in result["error"]
    assert source.read_text(encoding="utf-8") == "peer"
    assert preserved.read_text(encoding="utf-8") == "original"
    assert not destination.exists()


def test_file_move_cross_volume_directory_publishes_complete_tree(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    destination_dir = tmp_path / "other-volume"
    destination = destination_dir / "destination"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "payload.txt").write_text("complete", encoding="utf-8")
    destination_dir.mkdir()
    _simulate_cross_volume_rename(monkeypatch, source, destination)

    result = file_move(source.as_posix(), destination.as_posix())

    assert "error" not in result
    assert not source.exists()
    assert (destination / "nested" / "payload.txt").read_text(encoding="utf-8") == "complete"
    assert not list(tmp_path.glob(".*.move-source-*"))
    assert not list(destination_dir.glob(".*.move-target-*"))


def test_file_copy_rejects_source_replaced_after_validation(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.txt"
    preserved = tmp_path / "source-preserved.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("original", encoding="utf-8")
    from core.media import file_operations as file_tools

    real_copy = file_tools._copy_file_atomically

    def replace_before_copy(*args, **kwargs):
        source.rename(preserved)
        source.write_text("peer", encoding="utf-8")
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(
        file_tools,
        "_copy_file_atomically",
        replace_before_copy,
    )

    result = file_copy(source.as_posix(), destination.as_posix())

    assert "identity changed" in result["error"]
    assert source.read_text(encoding="utf-8") == "peer"
    assert preserved.read_text(encoding="utf-8") == "original"
    assert not destination.exists()


def test_file_move_cross_volume_copy_failure_restores_source(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    destination_dir = tmp_path / "other-volume"
    destination = destination_dir / "destination"
    source.mkdir()
    (source / "keep.txt").write_text("keep", encoding="utf-8")
    destination_dir.mkdir()
    _simulate_cross_volume_rename(monkeypatch, source, destination)

    def fail_after_partial_copy(_source: Path, staging: Path, **_kwargs):
        staging.mkdir()
        (staging / "partial.txt").write_text("partial", encoding="utf-8")
        raise OSError("copy interrupted")

    monkeypatch.setattr(
        "core.media.file_operations.copy_directory_without_links",
        fail_after_partial_copy,
    )

    result = file_move(source.as_posix(), destination.as_posix())

    assert "copy interrupted" in result["error"]
    assert (source / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.move-source-*"))
    assert not list(destination_dir.glob(".*.move-target-*"))


def test_file_extract_rejects_zip_backslash_traversal_without_partial_output(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "safe")
        zf.writestr(r"..\escape.txt", "bad")
    output = tmp_path / "out"

    result = file_extract(archive.as_posix(), output.as_posix())

    assert "error" in result
    assert not output.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_file_extract_rejects_tar_links_without_partial_output(tmp_path):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tf:
        content = b"safe"
        regular = tarfile.TarInfo("safe.txt")
        regular.size = len(content)
        tf.addfile(regular, io.BytesIO(content))
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../escape.txt"
        tf.addfile(link)
    output = tmp_path / "out"

    result = file_extract(archive.as_posix(), output.as_posix())

    assert "error" in result
    assert not output.exists()


def test_file_extract_backend_failure_preserves_existing_destination(tmp_path, monkeypatch):
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("new.txt", "new")
    output = tmp_path / "output"
    output.mkdir()
    old = output / "old.txt"
    old.write_text("old", encoding="utf-8")

    def fail_after_partial_write(_archive, staging):
        (staging / "partial.txt").write_text("partial", encoding="utf-8")
        raise OSError("read failed")

    monkeypatch.setattr("core.media.file_operations.extract_zip_safely", fail_after_partial_write)

    result = file_extract(archive.as_posix(), output.as_posix())

    assert "read failed" in result["error"]
    assert old.read_text(encoding="utf-8") == "old"
    assert not (output / "partial.txt").exists()
    assert not list(tmp_path.glob(".output.extract-*"))


def test_file_extract_rejects_existing_destination_symlink_descendant(tmp_path):
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("new.txt", "new")
    output = tmp_path / "output"
    external = tmp_path / "external.txt"
    output.mkdir()
    external.write_text("keep", encoding="utf-8")
    try:
        (output / "linked.txt").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    result = file_extract(archive.as_posix(), output.as_posix())

    assert "symbolic link" in result["error"]
    assert external.read_text(encoding="utf-8") == "keep"
    assert not (output / "new.txt").exists()


def test_file_extract_does_not_follow_destination_symlink(tmp_path):
    archive = tmp_path / "demo.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("new.txt", "new")
    external = tmp_path / "external"
    output_link = tmp_path / "output"
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        output_link.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    result = file_extract(archive.as_posix(), output_link.as_posix())

    assert "symbolic link" in result["error"]
    assert output_link.is_symlink()
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (external / "new.txt").exists()

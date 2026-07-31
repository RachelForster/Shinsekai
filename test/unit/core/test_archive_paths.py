from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.archive_paths import (
    UnsafeArchiveError,
    extract_tar_safely,
    extract_zip_safely,
    validate_archive_member_names,
    write_directory_to_zip_without_links,
    write_zip_files_without_links,
)


def test_safe_zip_extraction_writes_only_validated_regular_files(tmp_path):
    archive = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo-main/plugin.py", "plugin")
        zf.writestr("repo-main/assets/icon.png", b"png")
    target = tmp_path / "extract"

    with zipfile.ZipFile(archive) as zf:
        result = extract_zip_safely(zf, target, require_single_root=True)

    assert result.top_level == "repo-main"
    assert result.file_count == 2
    assert (target / "repo-main/plugin.py").read_text(encoding="utf-8") == "plugin"


def test_safe_zip_extraction_rejects_target_alias_before_writing(tmp_path):
    archive = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/plugin.py", "plugin")
    target_alias = f"{tmp_path.as_posix()}/nested/../extract"

    with zipfile.ZipFile(archive) as zf, pytest.raises(
        ValueError,
        match="lexical path aliases",
    ):
        extract_zip_safely(zf, target_alias)

    assert not (tmp_path / "extract").exists()


def test_safe_zip_extraction_rejects_relative_target_instead_of_using_cwd(
    tmp_path,
    monkeypatch,
):
    archive = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/plugin.py", "plugin")
    monkeypatch.chdir(tmp_path)

    with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="absolute"):
        extract_zip_safely(zf, "extract")

    assert not (tmp_path / "extract").exists()


def test_safe_zip_extraction_rejects_linked_target_parent(tmp_path):
    archive = tmp_path / "valid.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/plugin.py", "plugin")
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with zipfile.ZipFile(archive) as zf, pytest.raises(
        PermissionError,
        match="symbolic link component",
    ):
        extract_zip_safely(zf, alias / "extract")

    assert not (external / "extract").exists()


@pytest.mark.parametrize("archive_kind", ("zip", "tar"))
def test_safe_extraction_revalidates_target_after_creating_it(
    tmp_path,
    monkeypatch,
    archive_kind,
):
    archive = tmp_path / f"valid.{archive_kind}"
    if archive_kind == "zip":
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("repo/plugin.py", "plugin")
    else:
        with tarfile.open(archive, "w") as tf:
            content = b"plugin"
            member = tarfile.TarInfo("repo/plugin.py")
            member.size = len(content)
            tf.addfile(member, io.BytesIO(content))

    target = tmp_path / "extract"
    external = tmp_path / "external"
    external.mkdir()
    real_mkdir = Path.mkdir
    redirected = False

    def replace_new_target_with_link(path, *args, **kwargs):
        nonlocal redirected
        result = real_mkdir(path, *args, **kwargs)
        if path == target and not redirected:
            redirected = True
            path.rmdir()
            path.symlink_to(external, target_is_directory=True)
        return result

    monkeypatch.setattr(Path, "mkdir", replace_new_target_with_link)

    with pytest.raises(PermissionError, match="symbolic link component"):
        if archive_kind == "zip":
            with zipfile.ZipFile(archive) as zf:
                extract_zip_safely(zf, target)
        else:
            with tarfile.open(archive) as tf:
                extract_tar_safely(tf, target)

    assert target.is_symlink()
    assert list(external.iterdir()) == []


@pytest.mark.parametrize("archive_kind", ("zip", "tar"))
def test_safe_extraction_rejects_target_directory_replaced_after_preflight(
    archive_kind,
    tmp_path,
    monkeypatch,
):
    archive = tmp_path / f"valid.{archive_kind}"
    if archive_kind == "zip":
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("repo/plugin.py", "plugin")
    else:
        with tarfile.open(archive, "w") as tf:
            _write_tar_member(tf, "repo/plugin.py", b"plugin")

    target = tmp_path / "extract"
    target.mkdir()
    preserved = tmp_path / "preserved-extract"
    import core.archive_paths as archive_paths

    real_preflight = archive_paths._preflight_destinations

    def preflight_then_replace(*args, **kwargs):
        result = real_preflight(*args, **kwargs)
        target.rename(preserved)
        target.mkdir()
        return result

    monkeypatch.setattr(
        archive_paths,
        "_preflight_destinations",
        preflight_then_replace,
    )

    with pytest.raises(UnsafeArchiveError, match="changed identity"):
        if archive_kind == "zip":
            with zipfile.ZipFile(archive) as zf:
                extract_zip_safely(zf, target)
        else:
            with tarfile.open(archive) as tf:
                extract_tar_safely(tf, target)

    assert list(target.iterdir()) == []
    assert list(preserved.iterdir()) == []


@pytest.mark.parametrize(
    "member",
    [
        "../escape.py",
        r"..\escape.py",
        "/absolute.py",
        "/",
        "repo//",
        "~/repo/file.py",
        "repo/CON/file.py",
        "repo/trailing /file.py",
    ],
)
def test_safe_zip_extraction_rejects_nonportable_paths_before_writing(tmp_path, member):
    archive = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/valid.py", "valid")
        zf.writestr(member, "bad")
    target = tmp_path / "extract"

    with zipfile.ZipFile(archive) as zf, pytest.raises(UnsafeArchiveError):
        extract_zip_safely(zf, target)

    assert not target.exists()


def test_safe_zip_extraction_rejects_symbolic_link_entries(tmp_path):
    archive = tmp_path / "link.zip"
    link = zipfile.ZipInfo("repo/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/plugin.py", "plugin")
        zf.writestr(link, "../../outside")

    with zipfile.ZipFile(archive) as zf, pytest.raises(UnsafeArchiveError, match="link"):
        extract_zip_safely(zf, tmp_path / "extract")


def test_safe_zip_extraction_rejects_regular_file_with_directory_name(tmp_path):
    archive = tmp_path / "ambiguous.zip"
    regular = zipfile.ZipInfo("repo/file.txt/")
    regular.create_system = 3
    regular.external_attr = (stat.S_IFREG | 0o644) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(regular, "not a directory")

    with zipfile.ZipFile(archive) as zf, pytest.raises(
        UnsafeArchiveError,
        match="directory-shaped",
    ):
        extract_zip_safely(zf, tmp_path / "extract")

    assert not (tmp_path / "extract").exists()


def test_safe_zip_extraction_rejects_case_collisions_and_file_directory_collisions(tmp_path):
    case_archive = tmp_path / "case.zip"
    with zipfile.ZipFile(case_archive, "w") as zf:
        zf.writestr("repo/Assets/a.txt", "a")
        zf.writestr("repo/assets/b.txt", "b")
    with zipfile.ZipFile(case_archive) as zf, pytest.raises(UnsafeArchiveError, match="case"):
        extract_zip_safely(zf, tmp_path / "case-out")

    collision_archive = tmp_path / "collision.zip"
    with zipfile.ZipFile(collision_archive, "w") as zf:
        zf.writestr("repo/item/child.txt", "child")
        zf.writestr("repo/item", "file")
    with zipfile.ZipFile(collision_archive) as zf, pytest.raises(UnsafeArchiveError, match="conflicts"):
        extract_zip_safely(zf, tmp_path / "collision-out")


def test_safe_zip_extraction_rejects_unicode_normalization_collisions(tmp_path):
    archive = tmp_path / "unicode.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/caf\u00e9.txt", "composed")
        zf.writestr("repo/cafe\u0301.txt", "decomposed")

    with zipfile.ZipFile(archive) as zf, pytest.raises(UnsafeArchiveError, match="case"):
        extract_zip_safely(zf, tmp_path / "unicode-out")

    assert not (tmp_path / "unicode-out").exists()


def test_safe_zip_extraction_rejects_existing_link_ancestor_before_writing(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "extract"
    target.mkdir()
    (target / "repo").symlink_to(outside, target_is_directory=True)
    archive = tmp_path / "link-target.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "safe")
        zf.writestr("repo/plugin.py", "bad")

    with zipfile.ZipFile(archive) as zf, pytest.raises(UnsafeArchiveError, match="symbolic link"):
        extract_zip_safely(zf, target)

    assert not (target / "safe.txt").exists()
    assert not (outside / "plugin.py").exists()


def test_safe_zip_extraction_preflights_windows_reparse_ancestor_before_writing(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "extract"
    junction = target / "repo"
    junction.mkdir(parents=True)
    archive = tmp_path / "junction-target.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "must-not-be-written")
        zf.writestr("repo/plugin.py", "bad")
    original_lstat = Path.lstat

    def fake_lstat(path: Path):
        if path == junction:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(
                    stat,
                    "FILE_ATTRIBUTE_REPARSE_POINT",
                    0x00000400,
                ),
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)

    with zipfile.ZipFile(archive) as zf, pytest.raises(
        UnsafeArchiveError,
        match="reparse point",
    ):
        extract_zip_safely(zf, target)

    assert not (target / "safe.txt").exists()


def test_safe_zip_extraction_preflights_existing_file_ancestors_before_writing(tmp_path):
    target = tmp_path / "extract"
    target.mkdir()
    occupied_parent = target / "repo"
    occupied_parent.write_text("keep", encoding="utf-8")
    archive = tmp_path / "file-parent-target.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("safe.txt", "must-not-be-written")
        zf.writestr("repo/plugin.py", "bad")

    with zipfile.ZipFile(archive) as zf, pytest.raises(
        UnsafeArchiveError,
        match="parent conflicts",
    ):
        extract_zip_safely(zf, target)

    assert occupied_parent.read_text(encoding="utf-8") == "keep"
    assert not (target / "safe.txt").exists()


def _write_tar_member(tf: tarfile.TarFile, name: str, content: bytes = b"data") -> None:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    tf.addfile(member, io.BytesIO(content))


def test_safe_tar_extraction_writes_regular_files(tmp_path):
    archive = tmp_path / "valid.tar"
    with tarfile.open(archive, "w") as tf:
        _write_tar_member(tf, "repo/file.txt", b"ok")

    with tarfile.open(archive, "r") as tf:
        result = extract_tar_safely(tf, tmp_path / "out")

    assert result.top_level == "repo"
    assert result.file_count == 1
    assert (tmp_path / "out/repo/file.txt").read_bytes() == b"ok"


def test_safe_tar_extraction_rejects_target_alias_before_writing(tmp_path):
    archive = tmp_path / "valid.tar"
    with tarfile.open(archive, "w") as tf:
        _write_tar_member(tf, "repo/file.txt", b"ok")
    target_alias = f"{tmp_path.as_posix()}/./out"

    with tarfile.open(archive, "r") as tf, pytest.raises(
        ValueError,
        match="lexical path aliases",
    ):
        extract_tar_safely(tf, target_alias)

    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("member_name", ["../escape.txt", r"..\escape.txt", "repo/CON"])
def test_safe_tar_extraction_rejects_unsafe_paths_before_writing(tmp_path, member_name):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tf:
        _write_tar_member(tf, "safe.txt")
        _write_tar_member(tf, member_name)

    with tarfile.open(archive, "r") as tf, pytest.raises(UnsafeArchiveError):
        extract_tar_safely(tf, tmp_path / "out")

    assert not (tmp_path / "out").exists()


def test_safe_tar_extraction_rejects_links_before_writing(tmp_path):
    archive = tmp_path / "link.tar"
    with tarfile.open(archive, "w") as tf:
        _write_tar_member(tf, "repo/file.txt")
        link = tarfile.TarInfo("repo/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        tf.addfile(link)

    with tarfile.open(archive, "r") as tf, pytest.raises(UnsafeArchiveError, match="link"):
        extract_tar_safely(tf, tmp_path / "out")

    assert not (tmp_path / "out").exists()


def test_safe_tar_extraction_rejects_regular_file_with_directory_name(tmp_path):
    archive = tmp_path / "ambiguous.tar"
    with tarfile.open(archive, "w") as tf:
        _write_tar_member(tf, "repo/file.txt/")

    with tarfile.open(archive, "r") as tf, pytest.raises(
        UnsafeArchiveError,
        match="directory-shaped",
    ):
        extract_tar_safely(tf, tmp_path / "out")

    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "names",
    [
        ["../escape.txt"],
        [r"folder\..\escape.txt"],
        ["Folder/a.txt", "folder/b.txt"],
        ["folder", "folder/file.txt"],
        ["folder/file.txt", "folder/file.txt"],
        ["caf\u00e9/file.txt", "cafe\u0301/other.txt"],
        ["bundle//", "bundle/file.txt"],
        ["/", "bundle/file.txt"],
    ],
)
def test_generic_archive_member_preflight_rejects_unsafe_names(names):
    with pytest.raises(UnsafeArchiveError):
        validate_archive_member_names(names)


def test_generic_archive_member_preflight_accepts_portable_tree():
    validate_archive_member_names(["bundle/", "bundle/bin/", "bundle/bin/server.exe"])


def test_link_free_zip_writers_stream_portable_regular_files(tmp_path):
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    first = source / "manifest.json"
    second = nested / "asset.bin"
    first.write_text("{}", encoding="utf-8")
    second.write_bytes(b"asset")
    archive_path = tmp_path / "bundle.zip"

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        assert write_directory_to_zip_without_links(archive, source) == 2

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["manifest.json", "nested/asset.bin"]
        assert archive.read("nested/asset.bin") == b"asset"


def test_link_free_zip_writer_validates_complete_member_set_before_writing(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    archive_path = tmp_path / "bundle.zip"

    with zipfile.ZipFile(archive_path, "w") as archive, pytest.raises(
        UnsafeArchiveError,
        match="case",
    ):
        write_zip_files_without_links(
            archive,
            [(first, "Assets/File.txt"), (second, "assets/file.txt")],
        )

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == []


def test_directory_zip_writer_rejects_file_replaced_by_symlink_after_inventory(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    candidate = source / "asset.txt"
    external = tmp_path / "external.txt"
    candidate.write_text("safe", encoding="utf-8")
    external.write_text("secret", encoding="utf-8")
    try:
        probe = tmp_path / "probe"
        probe.symlink_to(external)
        probe.unlink()
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    import core.archive_paths as archive_paths

    real_inventory = archive_paths.inspect_portable_directory_tree_with_metadata

    def inventory_then_replace(root):
        inventory = real_inventory(root)
        candidate.unlink()
        candidate.symlink_to(external)
        return inventory

    monkeypatch.setattr(
        archive_paths,
        "inspect_portable_directory_tree_with_metadata",
        inventory_then_replace,
    )
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as archive, pytest.raises(
        PermissionError,
        match="symbolic link",
    ):
        write_directory_to_zip_without_links(archive, source)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == []


def test_directory_zip_writer_rejects_regular_file_replaced_after_inventory(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    candidate = source / "asset.txt"
    preserved = source / "preserved.txt"
    candidate.write_text("safe", encoding="utf-8")
    import core.archive_paths as archive_paths

    real_inventory = archive_paths.inspect_portable_directory_tree_with_metadata

    def inventory_then_replace(root):
        inventory = real_inventory(root)
        candidate.rename(preserved)
        candidate.write_text("peer", encoding="utf-8")
        return inventory

    monkeypatch.setattr(
        archive_paths,
        "inspect_portable_directory_tree_with_metadata",
        inventory_then_replace,
    )
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path, "w") as archive, pytest.raises(
        PermissionError,
        match="identity changed",
    ):
        write_directory_to_zip_without_links(archive, source)

    assert candidate.read_text(encoding="utf-8") == "peer"
    assert preserved.read_text(encoding="utf-8") == "safe"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == []


def test_zip_writer_rejects_in_place_source_mutation_before_member_publish(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "asset.txt"
    source.write_text("safe", encoding="utf-8")
    archive_path = tmp_path / "bundle.zip"
    import core.archive_paths as archive_paths

    real_copy = archive_paths.shutil.copyfileobj
    calls = 0

    def mutate_after_source_copy(input_file, output_file, *args, **kwargs):
        nonlocal calls
        result = real_copy(input_file, output_file, *args, **kwargs)
        calls += 1
        if calls == 1:
            source.write_text("replacement-is-longer", encoding="utf-8")
        return result

    monkeypatch.setattr(
        archive_paths.shutil,
        "copyfileobj",
        mutate_after_source_copy,
    )

    with zipfile.ZipFile(archive_path, "w") as archive, pytest.raises(
        PermissionError,
        match="changed while it was being read",
    ):
        write_zip_files_without_links(
            archive,
            [(source, "asset.txt")],
        )

    assert source.read_text(encoding="utf-8") == "replacement-is-longer"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == []

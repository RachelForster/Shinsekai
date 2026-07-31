from __future__ import annotations

from pathlib import Path

import pytest

from core.media import chat_attachments
from core.media.chat_attachments import (
    CHAT_ATTACHMENT_STAGE_SUBDIR,
    CHAT_ATTACHMENTS_ROOT_ENV,
    MAX_CHAT_ATTACHMENTS,
    _chat_attachment_root,
    chat_attachment_display_text,
    resolve_chat_attachments,
    stage_uploaded_chat_attachments,
)


@pytest.fixture(autouse=True)
def clear_attachment_root_cache():
    _chat_attachment_root.cache_clear()
    yield
    _chat_attachment_root.cache_clear()


def test_resolve_chat_attachments_derives_trusted_metadata_and_deduplicates(
    tmp_path: Path,
    monkeypatch,
):
    image = tmp_path / "scene.png"
    image.write_bytes(b"png")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, tmp_path.as_posix())

    attachments = resolve_chat_attachments(
        [
            {"kind": "image", "name": "spoofed.exe", "path": str(image)},
            {"kind": "image", "path": str(image)},
        ]
    )

    assert len(attachments) == 1
    assert attachments[0].name == "scene.png"
    assert attachments[0].mime_type == "image/png"
    assert attachments[0].path == image.resolve()
    assert attachments[0].to_payload()["path"] == "scene.png"


def test_resolve_chat_attachments_accepts_portable_relative_paths(
    tmp_path: Path,
    monkeypatch,
):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("notes", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, tmp_path.as_posix())

    attachment = resolve_chat_attachments(
        [{"kind": "file", "path": "notes.txt"}]
    )[0]

    assert attachment.path == text_file
    assert attachment.to_payload()["path"] == "notes.txt"
    with pytest.raises(ValueError, match="Unsupported chat image type"):
        resolve_chat_attachments([{"kind": "image", "path": str(text_file)}])


def test_relative_attachment_reference_survives_project_move(tmp_path: Path):
    key = "0123456789abcdef0123456789abcdef"
    old_path = tmp_path / "old/data/chat_attachments" / key / "notes.txt"
    new_root = tmp_path / "new/data/chat_attachments"
    new_path = new_root / key / "notes.txt"
    new_path.parent.mkdir(parents=True)
    new_path.write_text("migrated", encoding="utf-8")

    attachment = resolve_chat_attachments(
        [{"kind": "file", "path": old_path.as_posix()}],
        root=new_root,
    )[0]

    assert attachment.path == new_path
    assert attachment.to_payload()["path"] == f"{key}/notes.txt"


def test_attachment_paths_do_not_expand_user_home_aliases(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, "~/attachments")

    with pytest.raises(ValueError, match="absolute"):
        resolve_chat_attachments([{"kind": "file", "path": "~/notes.txt"}])
    with pytest.raises(ValueError, match="absolute"):
        stage_uploaded_chat_attachments(["~/upload.txt"], project_root=tmp_path)


def test_resolve_chat_attachments_rejects_outer_whitespace_without_retargeting(
    tmp_path: Path,
    monkeypatch,
):
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, tmp_path.as_posix())

    with pytest.raises(ValueError, match="surrounding whitespace"):
        resolve_chat_attachments([{"kind": "file", "path": f" {document}"}])


def test_resolve_chat_attachments_rejects_explicit_traversal_segments(tmp_path: Path):
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    traversal_path = tmp_path / "nested" / ".." / document.name

    with pytest.raises(ValueError, match="invalid traversal segments"):
        resolve_chat_attachments([{"kind": "file", "path": str(traversal_path)}])


def test_resolve_chat_attachments_rejects_paths_outside_configured_root(tmp_path: Path, monkeypatch):
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outside_root = tmp_path / "allowed-private"
    outside_root.mkdir()
    outside_file = outside_root / "private.txt"
    outside_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(allowed_root))

    with pytest.raises(ValueError, match="outside the allowed directory"):
        resolve_chat_attachments([{"kind": "file", "path": str(outside_file)}])


def test_resolve_chat_attachments_requires_configured_root(tmp_path: Path, monkeypatch):
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    monkeypatch.delenv(CHAT_ATTACHMENTS_ROOT_ENV, raising=False)

    with pytest.raises(ValueError, match=f"{CHAT_ATTACHMENTS_ROOT_ENV} must be configured"):
        resolve_chat_attachments([{"kind": "file", "path": str(document)}])


def test_resolve_chat_attachments_rejects_linked_configured_root(
    tmp_path: Path,
    monkeypatch,
):
    real_root = tmp_path / "real-root"
    root_alias = tmp_path / "root-alias"
    real_root.mkdir()
    document = real_root / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    try:
        root_alias.symlink_to(real_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, root_alias.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_chat_attachments([{"kind": "file", "path": document.as_posix()}])


def test_resolve_chat_attachments_rejects_linked_selected_file(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "allowed"
    root.mkdir()
    real_document = root / "real-notes.txt"
    document_alias = root / "notes.txt"
    real_document.write_text("notes", encoding="utf-8")
    try:
        document_alias.symlink_to(real_document)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, root.as_posix())

    with pytest.raises(PermissionError, match="symbolic link"):
        resolve_chat_attachments(
            [{"kind": "file", "path": document_alias.as_posix()}]
        )


def test_chat_attachment_display_uses_trusted_file_name(tmp_path: Path):
    document = tmp_path / "story.txt"
    document.write_text("Once upon a time", encoding="utf-8")
    attachments = resolve_chat_attachments([{"kind": "file", "path": str(document)}])

    assert chat_attachment_display_text("Summarize", attachments) == "Summarize\n[file: story.txt]"


def test_stage_uploaded_attachments_rejects_count_before_copying(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    sources = []
    for index in range(MAX_CHAT_ATTACHMENTS + 1):
        source = uploads / f"file-{index}.txt"
        source.write_text("x", encoding="utf-8")
        sources.append(source)
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))

    with pytest.raises(ValueError, match="at most"):
        stage_uploaded_chat_attachments(sources)

    assert not root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_stage_uploaded_attachments_rejects_source_alias_before_copying(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    upload = tmp_path / "uploads/note.txt"
    root.mkdir()
    upload.parent.mkdir()
    upload.write_text("note", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    alias = f"{upload.parent.as_posix()}/./{upload.name}"

    with pytest.raises(ValueError, match="lexical path aliases"):
        stage_uploaded_chat_attachments([alias])

    assert not root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_stage_uploaded_attachments_rejects_source_symlink_before_copying(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    external = tmp_path / "external.txt"
    alias = tmp_path / "upload.txt"
    root.mkdir()
    external.write_text("secret", encoding="utf-8")
    try:
        alias.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))

    with pytest.raises(PermissionError, match="symbolic link"):
        stage_uploaded_chat_attachments([alias])

    assert not root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_stage_uploaded_attachments_copies_validated_batch_inside_allowed_root(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    image = uploads / "scene.png"
    document = uploads / "notes.txt"
    image.write_bytes(b"png")
    document.write_text("notes", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))

    payloads = stage_uploaded_chat_attachments([image, document])
    stage_root = root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR)
    resolved = resolve_chat_attachments(payloads, root=stage_root)

    assert [attachment.kind for attachment in resolved] == ["image", "file"]
    assert [attachment.name for attachment in resolved] == ["scene.png", "notes.txt"]
    assert all(attachment.path.is_relative_to(root) for attachment in resolved)


def test_stage_uploaded_attachments_rejects_aggregate_size_before_copying(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    first = uploads / "first.txt"
    second = uploads / "second.txt"
    first.write_bytes(b"123")
    second.write_bytes(b"456")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    monkeypatch.setattr(chat_attachments, "MAX_CHAT_ATTACHMENTS_TOTAL_BYTES", 5)

    with pytest.raises(ValueError, match="total size"):
        stage_uploaded_chat_attachments([first, second])

    assert not root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_stage_uploaded_attachments_rechecks_copied_size_before_publication(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    upload = tmp_path / "uploads" / "growing.txt"
    root.mkdir()
    upload.parent.mkdir()
    upload.write_bytes(b"x")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    monkeypatch.setattr(chat_attachments, "MAX_CHAT_ATTACHMENT_BYTES", 5)

    def copy_grown_file(_source, directory, requested_name, **_kwargs):
        destination = Path(directory) / requested_name
        destination.write_bytes(b"123456")
        return destination, destination.lstat()

    monkeypatch.setattr(
        chat_attachments,
        "copy_file_exclusive_with_identity",
        copy_grown_file,
    )

    with pytest.raises(ValueError, match="too large"):
        stage_uploaded_chat_attachments([upload])

    stage_root = root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR)
    assert stage_root.is_dir()
    assert list(stage_root.iterdir()) == []


def test_stage_uploaded_attachments_rejects_source_changed_after_validation(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "project"
    upload = tmp_path / "uploads" / "changing.txt"
    root.mkdir()
    upload.parent.mkdir()
    upload.write_text("approved", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    real_copy = chat_attachments.copy_file_exclusive_with_identity
    changed = False

    def change_before_copy(source, *args, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            Path(source).write_text(
                "replacement-is-longer",
                encoding="utf-8",
            )
        return real_copy(source, *args, **kwargs)

    monkeypatch.setattr(
        chat_attachments,
        "copy_file_exclusive_with_identity",
        change_before_copy,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        stage_uploaded_chat_attachments([upload])

    stage_root = root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR)
    assert stage_root.is_dir()
    assert list(stage_root.iterdir()) == []


def test_stage_uploaded_attachments_rolls_back_partial_copy(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    first = uploads / "first.txt"
    second = uploads / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(root))
    real_copy = chat_attachments.copy_file_exclusive_with_identity
    copy_count = 0

    def fail_second_copy(*args, **kwargs):
        nonlocal copy_count
        copy_count += 1
        if copy_count == 2:
            raise OSError("copy failed")
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(
        chat_attachments,
        "copy_file_exclusive_with_identity",
        fail_second_copy,
    )

    with pytest.raises(OSError, match="copy failed"):
        stage_uploaded_chat_attachments([first, second])

    stage_root = root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR)
    assert stage_root.is_dir()
    assert list(stage_root.iterdir()) == []


def test_explicit_project_root_overrides_stale_attachment_environment(tmp_path: Path, monkeypatch):
    stale_root = tmp_path / "stale"
    selected_root = tmp_path / "selected"
    upload = tmp_path / "note.txt"
    stale_root.mkdir()
    selected_root.mkdir()
    upload.write_text("note", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, str(stale_root))

    payloads = stage_uploaded_chat_attachments([upload], project_root=selected_root)

    relative = Path(str(payloads[0]["path"]))
    assert not relative.is_absolute()
    assert (
        selected_root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR, relative).read_text(
            encoding="utf-8"
        )
        == "note"
    )
    assert not stale_root.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).exists()


def test_relative_attachment_root_environment_is_rejected(tmp_path: Path, monkeypatch):
    upload = tmp_path / "note.txt"
    upload.write_text("note", encoding="utf-8")
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, "relative-root")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        stage_uploaded_chat_attachments([upload])

    assert not (tmp_path / "relative-root").exists()


def test_attachment_paths_reject_lexical_aliases_before_resolution(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "allowed"
    root.mkdir()
    document = root / "note.txt"
    document.write_text("note", encoding="utf-8")

    monkeypatch.setenv(
        CHAT_ATTACHMENTS_ROOT_ENV,
        f"{tmp_path.as_posix()}/./allowed",
    )
    with pytest.raises(ValueError, match="lexical path aliases"):
        resolve_chat_attachments([{"kind": "file", "path": document.as_posix()}])

    _chat_attachment_root.cache_clear()
    monkeypatch.setenv(CHAT_ATTACHMENTS_ROOT_ENV, root.as_posix())
    with pytest.raises(ValueError, match="lexical path aliases"):
        resolve_chat_attachments(
            [{"kind": "file", "path": f"{root.as_posix()}//note.txt"}]
        )


def test_attachment_stage_symlink_cannot_escape_project(tmp_path: Path):
    project = tmp_path / "project"
    external = tmp_path / "external"
    upload = tmp_path / "note.txt"
    project.joinpath("data").mkdir(parents=True)
    external.mkdir()
    marker = external / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    upload.write_text("note", encoding="utf-8")
    try:
        project.joinpath(*CHAT_ATTACHMENT_STAGE_SUBDIR).symlink_to(
            external,
            target_is_directory=True,
        )
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        stage_uploaded_chat_attachments([upload], project_root=project)

    assert marker.read_text(encoding="utf-8") == "keep"

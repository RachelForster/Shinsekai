from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

import sdk.chat_ui_theme as chat_ui_theme
from sdk.chat_ui_theme import (
    MANIFEST_NAME,
    _main,
    locate_manifest_root,
    pack_theme,
    safe_extract,
    slugify_theme_id,
    validate_manifest,
    validate_theme_dir,
)


def _valid_manifest() -> dict:
    return {
        "schema": 1,
        "id": "valid-theme",
        "name": {"en": "Valid"},
        "author": "Tester",
        "version": "1.0.0",
        "description": "Demo theme",
        "preview": "assets/preview.png",
        "tokens": {
            "global": {"themeColor": "#123456", "fontFamily": "Arial"},
            "fonts": [{"family": "Demo", "src": "assets/demo.woff2", "weight": 400}],
            "dialog": {
                "background": "rgba(1,2,3,0.8)",
                "backgroundImage": "assets/dialog.png",
                "chrome": "panel",
                "frameImage": "assets/dialog-frame.svg",
                "frameOutsetPx": 5,
                "frameSlice": 36,
                "frameWidthPx": 14,
                "heightPx": 120,
                "nameInputGapVh": 20,
                "offsetY": -10,
                "padding": 16,
                "textAlign": "left",
                "textShadow": "0 1px 2px rgba(0,0,0,0.3)",
                "widthPct": 80,
            },
            "options": {
                "active": {"background": "rgba(40,40,40,0.9)"},
                "hover": {"color": "#ffffff"},
                "icon": "none",
                "placement": "center",
                "textShadow": "0 1px 2px rgba(0,0,0,0.4)",
                "widthMode": "fixed",
            },
            "input": {
                "fieldBackground": "rgba(20,20,20,0.7)",
                "fieldBorderRadius": "10px",
                "layout": "default",
                "sendPlacement": "outside",
            },
            "toolbar": {"placement": "input-top", "reveal": "always"},
            "name": {
                "align": "left",
                "decoration": "arrow-fade",
                "fontFamily": "Demo",
                "hideWhenStartOption": False,
                "overlapPx": 14,
                "textShadow": "0 1px 2px rgba(0,0,0,0.2)",
            },
            "logs": {
                "badge": {"background": "#333333"},
                "code": {"fontFamily": "monospace"},
                "panel": {
                    "frameImage": "assets/logs-frame.svg",
                    "frameOutsetPx": 4,
                    "frameSlice": 24,
                    "frameWidthPx": 8,
                },
                "fileItem": {
                    "active": {"background": "#222222"},
                    "hover": {"background": "#111111"},
                },
                "levels": {"warn": {"color": "#ffee88"}},
                "line": {
                    "expanded": {"background": "#202020"},
                    "hover": {"background": "#303030"},
                },
            },
            "typewriter": {"cps": 25, "sound": "assets/type.wav"},
        },
    }


def _write_theme(root: Path, manifest: dict | None = None) -> Path:
    theme_dir = root / "theme"
    assets = theme_dir / "assets"
    assets.mkdir(parents=True)
    data = manifest or _valid_manifest()
    (theme_dir / MANIFEST_NAME).write_text(json.dumps(data), encoding="utf-8")
    for name in ("preview.png", "demo.woff2", "dialog-frame.svg", "dialog.png", "logs-frame.svg", "type.wav"):
        (assets / name).write_bytes(b"asset")
    return theme_dir


def test_slugify_and_validate_manifest_normalizes_rich_theme() -> None:
    assert slugify_theme_id(" Demo Theme! ") == "demo-theme"
    assert slugify_theme_id("!!!") == "theme"
    assert slugify_theme_id("CON") == "theme-con"
    assert slugify_theme_id("LPT1") == "theme-lpt1"

    result = validate_manifest(_valid_manifest())

    assert result.ok is True
    assert result.normalized["author"] == "Tester"
    assert result.normalized["preview"] == "assets/preview.png"
    assert result.normalized["tokens"]["dialog"]["chrome"] == "panel"
    assert result.normalized["tokens"]["dialog"]["frameOutsetPx"] == 5
    assert result.normalized["tokens"]["dialog"]["frameWidthPx"] == 14
    assert result.normalized["tokens"]["options"]["active"]["background"] == "rgba(40,40,40,0.9)"
    assert result.normalized["tokens"]["input"]["sendPlacement"] == "outside"
    assert result.normalized["tokens"]["name"]["overlapPx"] == 14
    assert result.normalized["tokens"]["name"]["decoration"] == "arrow-fade"
    assert result.normalized["tokens"]["logs"]["levels"]["warn"]["color"] == "#ffee88"
    assert result.normalized["tokens"]["logs"]["panel"]["frameSlice"] == 24
    assert result.normalized["tokens"]["typewriter"]["sound"] == "assets/type.wav"


def test_validate_manifest_rejects_theme_id_outer_whitespace_without_retargeting() -> None:
    manifest = _valid_manifest()
    manifest["id"] = " demo-theme "

    result = validate_manifest(manifest)

    assert result.ok is False
    assert result.normalized["id"] == " demo-theme "
    assert any("首尾" in error for error in result.errors)


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        {"schema": 2, "id": "bad", "name": {"en": "Bad"}, "tokens": {}},
        {"schema": 1, "id": "-bad", "name": {"en": "Bad"}, "tokens": {}},
        {"schema": 1, "id": "bad", "name": {}, "tokens": {}},
        {"schema": 1, "id": "bad", "name": {"en": "Bad"}, "tokens": []},
        {
            "schema": 1,
            "id": "bad",
            "name": {"en": "Bad"},
            "tokens": {"dialog": {"background": "red; position:absolute"}},
        },
        {
            "schema": 1,
            "id": "bad",
            "name": {"en": "Bad"},
            "tokens": {"typewriter": {"sound": "../escape.wav"}},
            "preview": "https://example.test/preview.png",
        },
    ],
)
def test_validate_manifest_rejects_invalid_shapes(manifest) -> None:
    result = validate_manifest(manifest)

    assert result.ok is False
    assert result.errors


@pytest.mark.parametrize(
    "asset_ref",
    [
        " assets/preview.png",
        "assets/preview.png ",
        "assets/bad\nname.png",
        "./assets/preview.png",
        "assets//preview.png",
        "assets/../preview.png",
        "assets/preview.png/",
    ],
)
def test_validate_manifest_rejects_nonportable_asset_reference_text(asset_ref: str) -> None:
    manifest = _valid_manifest()
    manifest["preview"] = asset_ref

    result = validate_manifest(manifest)

    assert result.ok is False
    assert any("preview" in error for error in result.errors)


@pytest.mark.parametrize(
    "tokens",
    [
        {"send": {"frameOutsetPx": 2}},
        {"options": {"hover": {"frameWidthPx": 8}}},
        {"logs": {"line": {"frameWidthPx": 8}}},
        {"logs": {"fileItem": {"active": {"frameOutsetPx": 2}}}},
    ],
)
def test_validate_manifest_rejects_frames_on_components_without_frame_layers(tokens: dict) -> None:
    manifest = _valid_manifest()
    manifest["tokens"] = tokens

    result = validate_manifest(manifest)

    assert result.ok is False
    assert any("不是规范允许的字段" in error for error in result.errors)


def test_validate_manifest_keeps_schema_one_legacy_frames_on_unsupported_blocks_compatible() -> None:
    manifest = _valid_manifest()
    manifest["tokens"] = {
        "send": {"frameImage": "assets/legacy.svg", "frameSlice": 24},
        "logs": {"line": {"frameImage": "assets/legacy.svg", "frameSlice": 16}},
    }

    result = validate_manifest(manifest)

    assert result.ok is True
    assert result.normalized["tokens"]["send"]["frameImage"] == "assets/legacy.svg"
    assert result.normalized["tokens"]["logs"]["line"]["frameSlice"] == 16


def test_validate_theme_dir_warns_for_missing_assets_and_reports_bad_json(tmp_path: Path) -> None:
    theme_dir = _write_theme(tmp_path)
    (theme_dir / "assets" / "dialog.png").unlink()

    result = validate_theme_dir(theme_dir)

    assert result.ok is True
    assert any("assets/dialog.png" in warning for warning in result.warnings)

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / MANIFEST_NAME).write_text("{", encoding="utf-8")
    assert validate_theme_dir(broken).ok is False
    assert validate_theme_dir(tmp_path / "missing").ok is False


def test_pack_theme_extracts_safely_and_locates_manifest_root(tmp_path: Path) -> None:
    theme_dir = _write_theme(tmp_path)
    output = tmp_path / "dist" / "theme.zip"

    assert pack_theme(theme_dir, output) == output
    assert output.is_file()

    extracted = tmp_path / "extracted"
    assert safe_extract(output, extracted) == extracted
    assert locate_manifest_root(extracted) == extracted

    nested = tmp_path / "nested"
    nested_theme = nested / "one"
    nested_theme.mkdir(parents=True)
    (nested_theme / MANIFEST_NAME).write_text("{}", encoding="utf-8")
    assert locate_manifest_root(nested) == nested_theme
    assert locate_manifest_root(tmp_path / "dist") is None


def test_theme_sdk_rejects_source_and_output_path_aliases(tmp_path: Path) -> None:
    theme_dir = _write_theme(tmp_path)
    source_alias = f"{tmp_path.as_posix()}/./theme"
    output_alias = f"{tmp_path.as_posix()}/dist/../theme.zip"

    with pytest.raises(ValueError, match="lexical path aliases"):
        validate_theme_dir(source_alias)
    with pytest.raises(ValueError, match="lexical path aliases"):
        pack_theme(theme_dir, output_alias)

    assert not (tmp_path / "theme.zip").exists()


def test_theme_sdk_rejects_extraction_target_alias_before_writing(tmp_path: Path) -> None:
    zip_path = tmp_path / "theme.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("theme.json", "{}")
    output_alias = f"{tmp_path.as_posix()}/./out"

    with pytest.raises(ValueError, match="lexical path aliases"):
        safe_extract(zip_path, output_alias)

    assert not (tmp_path / "out").exists()


def test_theme_sdk_rejects_linked_external_output_parent(tmp_path: Path) -> None:
    theme_dir = _write_theme(tmp_path)
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        pack_theme(theme_dir, alias / "theme.zip")

    assert list(external.iterdir()) == []


def test_theme_sdk_rejects_linked_external_extraction_parent(tmp_path: Path) -> None:
    zip_path = tmp_path / "theme.zip"
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    external.mkdir()
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("theme.json", "{}")
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        safe_extract(zip_path, alias / "theme")

    assert list(external.iterdir()) == []


@pytest.mark.parametrize("member", ["../escape.txt", r"..\escape.txt"])
def test_safe_extract_rejects_zip_slip_entries(tmp_path: Path, member: str) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(member, "bad")

    with pytest.raises(ValueError, match="路径穿越"):
        safe_extract(zip_path, tmp_path / "out")


def test_safe_extract_rejects_link_entries_before_writing(tmp_path: Path) -> None:
    zip_path = tmp_path / "link.zip"
    link = zipfile.ZipInfo("assets/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("theme.json", "{}")
        zf.writestr(link, "../../outside")

    output = tmp_path / "out"
    with pytest.raises(ValueError, match="非便携路径"):
        safe_extract(zip_path, output)

    assert not output.exists()


def test_safe_extract_rejects_symlinked_archive_path(tmp_path: Path) -> None:
    archive = tmp_path / "theme.zip"
    alias = tmp_path / "theme-alias.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("theme.json", "{}")
    try:
        alias.symlink_to(archive)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        safe_extract(alias, tmp_path / "out")

    assert not (tmp_path / "out").exists()


def test_locate_manifest_root_rejects_symlinked_nested_theme(tmp_path: Path) -> None:
    extracted = tmp_path / "extracted"
    external = tmp_path / "external-theme"
    extracted.mkdir()
    external.mkdir()
    (external / MANIFEST_NAME).write_text("{}", encoding="utf-8")
    try:
        (extracted / "theme").symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable")

    assert locate_manifest_root(extracted) is None


def test_pack_theme_rejects_invalid_manifest(tmp_path: Path) -> None:
    theme_dir = _write_theme(
        tmp_path,
        {"schema": 1, "id": "bad", "name": {"en": "Bad"}, "tokens": {"unknown": {}}},
    )

    with pytest.raises(ValueError, match="主题校验失败"):
        pack_theme(theme_dir, tmp_path / "bad.zip")


def test_theme_validation_and_pack_reject_symlinked_resources(tmp_path: Path) -> None:
    theme_dir = _write_theme(tmp_path)
    external = tmp_path / "external.txt"
    external.write_text("secret", encoding="utf-8")
    try:
        (theme_dir / "linked.txt").symlink_to(external)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    result = validate_theme_dir(theme_dir)
    assert result.ok is False
    assert any("符号链接" in error for error in result.errors)
    with pytest.raises(ValueError, match="主题校验失败"):
        pack_theme(theme_dir, tmp_path / "linked.zip")


def test_pack_theme_rejects_output_inside_source_tree(tmp_path: Path) -> None:
    theme_dir = _write_theme(tmp_path)
    output = theme_dir / "theme.zip"

    with pytest.raises(ValueError, match="主题目录内部"):
        pack_theme(theme_dir, output)

    assert not output.exists()


def test_pack_theme_preserves_previous_output_when_source_changes_after_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    theme_dir = _write_theme(tmp_path)
    candidate = theme_dir / "assets" / "preview.png"
    external = tmp_path / "external.png"
    external.write_bytes(b"secret")
    output = tmp_path / "theme.zip"
    output.write_bytes(b"previous package")
    try:
        probe = tmp_path / "probe"
        probe.symlink_to(external)
        probe.unlink()
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    real_validate = chat_ui_theme.validate_theme_dir

    def validate_then_replace(path):
        result = real_validate(path)
        candidate.unlink()
        candidate.symlink_to(external)
        return result

    monkeypatch.setattr(
        chat_ui_theme,
        "validate_theme_dir",
        validate_then_replace,
    )

    with pytest.raises(PermissionError, match="symbolic link"):
        pack_theme(theme_dir, output)

    assert output.read_bytes() == b"previous package"


def test_cli_validate_and_pack_return_codes(tmp_path: Path, capsys) -> None:
    theme_dir = _write_theme(tmp_path)
    output = tmp_path / "theme.zip"

    assert _main(["validate", str(theme_dir)]) == 0
    assert "OK" in capsys.readouterr().out
    assert _main(["pack", str(theme_dir), "-o", str(output)]) == 0
    assert "packed ->" in capsys.readouterr().out

    broken = tmp_path / "broken-cli"
    broken.mkdir()
    assert _main(["validate", str(broken)]) == 1
    assert "FAILED" in capsys.readouterr().out

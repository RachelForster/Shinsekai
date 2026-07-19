from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

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
            "global": {"themeColor": "#123456", "fontFamily": "Arial", "windowScale": 0.9},
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
                "fontFamily": "Demo",
                "nameInputGapVh": 20,
                "offsetY": -10,
                "opacity": 0.75,
                "padding": 16,
                "scale": 1.1,
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
                "decoration": "accent",
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

    result = validate_manifest(_valid_manifest())

    assert result.ok is True
    assert result.normalized["author"] == "Tester"
    assert result.normalized["preview"] == "assets/preview.png"
    assert result.normalized["tokens"]["dialog"]["chrome"] == "panel"
    assert result.normalized["tokens"]["dialog"]["opacity"] == 0.75
    assert result.normalized["tokens"]["dialog"]["scale"] == 1.1
    assert result.normalized["tokens"]["dialog"]["fontFamily"] == "Demo"
    assert result.normalized["tokens"]["global"]["windowScale"] == 0.9
    assert result.normalized["tokens"]["dialog"]["frameOutsetPx"] == 5
    assert result.normalized["tokens"]["dialog"]["frameWidthPx"] == 14
    assert result.normalized["tokens"]["options"]["active"]["background"] == "rgba(40,40,40,0.9)"
    assert result.normalized["tokens"]["input"]["sendPlacement"] == "outside"
    assert result.normalized["tokens"]["name"]["overlapPx"] == 14
    assert result.normalized["tokens"]["logs"]["levels"]["warn"]["color"] == "#ffee88"
    assert result.normalized["tokens"]["logs"]["panel"]["frameSlice"] == 24
    assert result.normalized["tokens"]["typewriter"]["sound"] == "assets/type.wav"


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


def test_safe_extract_rejects_zip_slip_entries(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escape.txt", "bad")

    with pytest.raises(ValueError, match="路径穿越"):
        safe_extract(zip_path, tmp_path / "out")


def test_pack_theme_rejects_invalid_manifest(tmp_path: Path) -> None:
    theme_dir = _write_theme(
        tmp_path,
        {"schema": 1, "id": "bad", "name": {"en": "Bad"}, "tokens": {"unknown": {}}},
    )

    with pytest.raises(ValueError, match="主题校验失败"):
        pack_theme(theme_dir, tmp_path / "bad.zip")


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

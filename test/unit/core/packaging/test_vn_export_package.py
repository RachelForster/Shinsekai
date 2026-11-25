from __future__ import annotations

import json
from pathlib import Path
import re
import zipfile

import pytest

from core.packaging.vn_export_package import (
    VnExportOptions,
    VnRawEntry,
    export_playable_vn_package,
)


def _create_sample_assets(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "bg.png": b"\x89PNG\r\n\x1a\nbg-bytes",
        "cg.mp4": b"ftypmp42-cg-video",
        "bgm.mp3": b"ID3-bgm-bytes",
        "ambient.webm": b"\x1aE\xdf\xa3ambient-video",
        "ambient_rain.ogg": b"OggS-ambient-audio",
        "sprite_static.png": b"\x89PNG\r\n\x1a\nsprite-static",
        "sprite_video.webm": b"\x1aE\xdf\xa3sprite-video",
        "portrait.png": b"\x89PNG\r\n\x1a\nportrait",
        "voice1.wav": b"RIFF0000WAVEfmt ",
    }
    created: dict[str, Path] = {}
    for name, content in files.items():
        path = root / name
        path.write_bytes(content)
        created[name] = path
    return created


def _extract_story_payload(js_text: str) -> dict:
    prefix = "window.__SHINSEKAI_VN__="
    assert js_text.startswith(prefix)
    body = js_text[len(prefix) :].rstrip(";\r\n")
    return json.loads(body.replace("<\\/", "</"))


def test_export_zip_deduplicates_assets_escapes_script_and_skips_non_static(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _create_sample_assets(tmp_path / "src")
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)

    entries = [
        VnRawEntry(
            id="e1",
            role="assistant",
            speaker="Nanami",
            text="Hello </script> world!",
            options=("Choice A", "Choice B"),
            selected_index=1,
            background="bg.png",
            bgm="bgm.mp3",
            cg="cg.mp4",
            ambient_effects=(
                {"key": "rain", "url": "ambient.webm", "audioUrl": "ambient_rain.ogg", "layer": "front"},
            ),
            sprites=(
                {"id": "s1", "characterName": "Nanami", "path": "sprite_static.png", "avatarType": "static", "slot": 0, "scale": 1.1},
                {"id": "s2", "characterName": "Vid", "path": "sprite_video.webm", "avatarType": "static", "slot": 1},
                {"id": "l2d", "characterName": "L2D", "path": "model.state.json", "avatarType": "l2d"},
                {"id": "mmd", "characterName": "MMD", "path": "/api/avatar/file?model_path=mmd.pmx&path=s.json", "avatarType": "mmd"},
            ),
            stats=({"icon": "heart", "label": "Affinity", "value": 80, "max": 100},),
            player_portrait={"characterName": "You", "url": "portrait.png", "crop": {"x": 0.5, "y": 0.2, "zoom": 1}},
            voice_paths=(src["voice1.wav"],),
            voice_volume=0.85,
        ),
        VnRawEntry(
            id="e2",
            role="user",
            speaker="You",
            text="Next line",
            background="bg.png",
            bgm="bgm.mp3",
        ),
    ]

    zip_path = tmp_path / "out" / "story.zip"
    result = export_playable_vn_package(
        entries,
        VnExportOptions(
            title="Test VN",
            subtitle="Sub",
            locale="en",
            story_id="story-123",
            output_format="zip",
            output_path=zip_path,
            theme_vars={"--vn-accent": "#ff4488", "--bad": "url(x);"},
            ui_labels={"start": "Play"},
        ),
        resolve_asset=lambda ref: src.get(ref),
    )

    assert result.format == "zip"
    assert zip_path.is_file()
    assert result.entry_count == 2
    assert result.voice_count == 1
    assert result.transcoded_voice_count == 0
    assert result.skipped_non_static_sprites == 2
    assert result.index_html_bytes < 1024 * 1024
    assert "ffmpeg_unavailable" in result.warnings
    assert "skipped_non_static_sprites" in result.warnings

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "index.html" in names
        index_html = zf.read("index.html").decode("utf-8")
        assert "--vn-accent: #ff4488;" in index_html
        assert "--bad" not in index_html
        assert not re.search(r'(?:src|href)=["\']/', index_html)

        data_files = [n for n in names if n.startswith("story-data.") and n.endswith(".js")]
        style_files = [n for n in names if n.startswith("style.") and n.endswith(".css")]
        player_files = [n for n in names if n.startswith("player.") and n.endswith(".js")]
        assert len(data_files) == 1
        assert len(style_files) == 1
        assert len(player_files) == 1

        raw_js = zf.read(data_files[0]).decode("utf-8")
        assert "</script>" not in raw_js
        payload = _extract_story_payload(raw_js)
        assert payload["entries"][0]["text"] == "Hello </script> world!"
        assert len(payload["entries"][0]["sprites"]) == 2
        assert payload["entries"][0]["sprites"][0]["url"].startswith("./assets/sprites/")
        assert payload["entries"][0]["voices"][0].startswith("./assets/voice/")
        assert payload["entries"][0]["background"] == payload["entries"][1]["background"]
        assert payload["meta"]["coverIsVideo"] is True


def test_export_directory_with_mp3_transcode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _create_sample_assets(tmp_path / "src")
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): "ffmpeg")

    def fake_transcode(_bin: str, _src: Path, target: Path, **_kwargs) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3-mp3-transcoded")
        return True

    monkeypatch.setattr("core.packaging.vn_export_package.transcode_audio_to_mp3", fake_transcode)

    out_dir = tmp_path / "vn_dir"
    result = export_playable_vn_package(
        [VnRawEntry(id="e1", role="assistant", speaker="Mio", text="Hi", voice_paths=(src["voice1.wav"],))],
        VnExportOptions(
            title="Dir VN",
            subtitle="",
            locale="zh_CN",
            story_id="dir-1",
            output_format="directory",
            output_path=out_dir,
            include_bgm=False,
            include_ambient=False,
        ),
        resolve_asset=lambda ref: src.get(ref),
    )

    assert result.format == "directory"
    assert (out_dir / "index.html").is_file()
    assert result.transcoded_voice_count == 1
    assert result.warnings == ()
    voice_files = list((out_dir / "assets" / "voice").glob("*.mp3"))
    assert len(voice_files) == 1


def test_publish_directory_recovers_orphaned_backup_and_handles_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    src = _create_sample_assets(tmp_path / "src")
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)

    out_dir = tmp_path / "vn_out"
    orphaned_backup = tmp_path / ".vn_out.bak.crashed"
    orphaned_backup.mkdir(parents=True)
    (orphaned_backup / "stale.txt").write_text("old", encoding="utf-8")

    # Even if swap fails right after backup, an orphaned backup at target.parent is recovered first.
    from core.packaging.vn_export_package import _publish_directory

    stage_bad = tmp_path / "stage_bad"
    stage_bad.mkdir()

    real_replace = __import__("os").replace

    def fail_second_replace(src_p, dst_p):
        if Path(dst_p) == out_dir and Path(src_p).name.startswith(".vn_out.tmp."):
            raise OSError("simulated swap failure")
        return real_replace(src_p, dst_p)

    monkeypatch.setattr("core.packaging.vn_export_package.os.replace", fail_second_replace)
    with pytest.raises(OSError):
        _publish_directory(stage_bad, out_dir)
    assert out_dir.is_dir() and (out_dir / "stale.txt").is_file()

    monkeypatch.undo()

    # Concurrent exports to the exact same directory finish cleanly without colliding backup dirs.
    def run_export(i: int) -> Path:
        res = export_playable_vn_package(
            [VnRawEntry(id=f"e-{i}", role="assistant", speaker="Mio", text=f"Line {i}")],
            VnExportOptions(
                title=f"Concurrent {i}",
                subtitle="",
                locale="en",
                story_id=f"conc-{i}",
                output_format="directory",
                output_path=out_dir,
                include_voices=False,
                include_bgm=False,
                include_ambient=False,
            ),
            resolve_asset=lambda ref: src.get(ref),
        )
        return res.output_path

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run_export, range(6)))

    assert all(p == out_dir for p in results)
    assert (out_dir / "index.html").is_file()
    assert not list(tmp_path.glob(".vn_out.bak.*"))


def test_export_preserves_sparse_slots_and_player_sorts_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _create_sample_assets(tmp_path / "src")
    monkeypatch.setattr("core.packaging.vn_export_package.find_ffmpeg", lambda _roots=(): None)

    out_dir = tmp_path / "sparse_dir"
    export_playable_vn_package(
        [
            VnRawEntry(
                id="e1",
                role="assistant",
                speaker="Bob",
                text="Two sparse slots",
                sprites=(
                    {"id": "bob", "characterName": "Bob", "path": "sprite_static.png", "avatarType": "static", "slot": 2},
                    {"id": "alice", "characterName": "Alice", "path": "sprite_video.webm", "avatarType": "static", "slot": 1},
                ),
            )
        ],
        VnExportOptions(
            title="Sparse Slots",
            subtitle="",
            locale="en",
            story_id="sparse-1",
            output_format="directory",
            output_path=out_dir,
            include_voices=False,
            include_bgm=False,
            include_ambient=False,
        ),
        resolve_asset=lambda ref: src.get(ref),
    )
    player_files = list(out_dir.glob("player.*.js"))
    assert len(player_files) == 1
    player_js = player_files[0].read_text(encoding="utf-8")
    assert "spriteAxisCenter(rank, valid.length)" in player_js
    assert "valid.sort(" in player_js

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from frontend_bridge_core.music import _run_music_cover


def _music_state(project_root_dir=None):
    values = dict(
        config_manager=SimpleNamespace(
            config=SimpleNamespace(system_config=SimpleNamespace()),
        ),
        task_lock=threading.Lock(),
        tasks={"music-task": {"logs": []}},
    )
    if project_root_dir is not None:
        values["project_root_dir"] = project_root_dir
    return SimpleNamespace(**values)


def _patch_pipeline(monkeypatch, final_mix):
    monkeypatch.setattr(
        "live.music_cover_pipeline.run_pipeline",
        lambda *_args, **_kwargs: SimpleNamespace(final_mix=final_mix),
    )
    monkeypatch.setattr(
        "live.music_cover_pipeline.format_pipeline_log",
        lambda _result: "pipeline complete",
    )


def test_music_cover_result_uses_the_validated_regular_final_mix(
    monkeypatch,
    tmp_path,
):
    final_mix = tmp_path / "final mix.wav"
    final_mix.write_bytes(b"RIFF")
    _patch_pipeline(monkeypatch, final_mix)

    result = _run_music_cover(
        _music_state(),
        "music-task",
        {"query": "song", "source": "youtube"},
    )

    assert result == {
        "audioPath": str(final_mix),
        "log": "pipeline complete",
    }


@pytest.mark.parametrize("invalid_kind", ["missing", "directory"])
def test_music_cover_result_rejects_a_non_file_final_mix(
    monkeypatch,
    tmp_path,
    invalid_kind,
):
    final_mix = tmp_path / "final_mix.wav"
    if invalid_kind == "directory":
        final_mix.mkdir()
    _patch_pipeline(monkeypatch, final_mix)

    with pytest.raises(FileNotFoundError):
        _run_music_cover(
            _music_state(),
            "music-task",
            {"query": "song", "source": "youtube"},
        )


def test_music_cover_result_rejects_a_linked_final_mix(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "actual.wav"
    target.write_bytes(b"RIFF")
    final_mix = tmp_path / "final_mix.wav"
    try:
        final_mix.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")
    _patch_pipeline(monkeypatch, final_mix)

    with pytest.raises(PermissionError, match="symbolic link"):
        _run_music_cover(
            _music_state(),
            "music-task",
            {"query": "song", "source": "youtube"},
        )


def test_music_cover_result_requires_the_pipeline_to_return_a_final_mix(
    monkeypatch,
):
    _patch_pipeline(monkeypatch, None)

    with pytest.raises(FileNotFoundError, match="did not produce"):
        _run_music_cover(
            _music_state(),
            "music-task",
            {"query": "song", "source": "youtube"},
        )


def test_music_cover_pipeline_receives_bridge_project_root(
    monkeypatch,
    tmp_path,
):
    ambient = tmp_path / "ambient-project"
    selected = tmp_path / "selected-project"
    final_mix = selected / "data/music_cover/final.wav"
    ambient.mkdir()
    final_mix.parent.mkdir(parents=True)
    final_mix.write_bytes(b"RIFF")
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", ambient.as_posix())
    observed = {}

    def fake_pipeline(*_args, **kwargs):
        observed["root"] = kwargs.get("root")
        return SimpleNamespace(final_mix=final_mix)

    monkeypatch.setattr(
        "live.music_cover_pipeline.run_pipeline",
        fake_pipeline,
    )
    monkeypatch.setattr(
        "live.music_cover_pipeline.format_pipeline_log",
        lambda _result: "pipeline complete",
    )

    _run_music_cover(
        _music_state(selected),
        "music-task",
        {"query": "song", "source": "youtube"},
    )

    assert observed["root"] == selected.resolve()

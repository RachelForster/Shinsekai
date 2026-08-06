from __future__ import annotations

from application.runtime.restart_debug import (
    _restart_debug_log_path,
    write_restart_debug_log,
)


def test_restart_debug_log_ignores_relative_environment_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SHINSEKAI_RESTART_LOG", "relative.log")
    unrelated = tmp_path / "unrelated"
    temporary = tmp_path / "temporary"
    unrelated.mkdir()
    temporary.mkdir()
    monkeypatch.chdir(unrelated)

    assert _restart_debug_log_path(temp_dir=temporary) == (
        temporary / "shinsekai-restart-debug.log"
    )


def test_restart_debug_log_does_not_expand_user_home_alias(tmp_path, monkeypatch):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setenv("SHINSEKAI_RESTART_LOG", "~/restart.log")

    assert _restart_debug_log_path(temp_dir=temporary) == (
        temporary / "shinsekai-restart-debug.log"
    )


def test_restart_debug_log_disables_relative_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("SHINSEKAI_RESTART_LOG", raising=False)
    monkeypatch.chdir(tmp_path)

    assert _restart_debug_log_path(temp_dir="relative-temp") is None


def test_restart_debug_log_ignores_nonportable_environment_path(tmp_path, monkeypatch):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setenv("SHINSEKAI_RESTART_LOG", str(tmp_path / "bad\nrestart.log"))

    assert _restart_debug_log_path(temp_dir=temporary) == (
        temporary / "shinsekai-restart-debug.log"
    )


def test_restart_debug_log_ignores_lexical_absolute_alias(tmp_path, monkeypatch):
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setenv(
        "SHINSEKAI_RESTART_LOG",
        f"{tmp_path.as_posix()}/./restart.log",
    )

    assert _restart_debug_log_path(temp_dir=temporary) == (
        temporary / "shinsekai-restart-debug.log"
    )


def test_restart_debug_log_cannot_inject_a_desktop_recovery_line(tmp_path, monkeypatch):
    log = tmp_path / "restart.log"
    monkeypatch.setenv("SHINSEKAI_RESTART_LOG", str(log))

    write_restart_debug_log(
        "bridge",
        "failed\ncomponent=desktop setup resolved project_root=/fake app_root=/fake",
    )

    contents = log.read_text(encoding="utf-8")
    assert contents.count("\n") == 1
    assert "failed\\ncomponent=desktop" in contents


def test_restart_debug_log_does_not_follow_configured_symlink(tmp_path, monkeypatch):
    target = tmp_path / "target.log"
    link = tmp_path / "restart.log"
    target.write_text("keep\n", encoding="utf-8")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        import pytest

        pytest.skip("symbolic links are unavailable")
    fallback = tmp_path / "temporary"
    fallback.mkdir()
    monkeypatch.setenv("SHINSEKAI_RESTART_LOG", str(link))
    monkeypatch.setattr(
        "application.runtime.restart_debug.tempfile.gettempdir",
        lambda: str(fallback),
    )

    write_restart_debug_log("bridge", "safe")

    assert target.read_text(encoding="utf-8") == "keep\n"
    assert (fallback / "shinsekai-restart-debug.log").is_file()


def test_restart_debug_log_falls_back_from_intermediate_symlink(tmp_path, monkeypatch):
    external = tmp_path / "external"
    alias = tmp_path / "alias"
    fallback = tmp_path / "temporary"
    external.mkdir()
    fallback.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        import pytest

        pytest.skip("symbolic links are unavailable")
    monkeypatch.setenv("SHINSEKAI_RESTART_LOG", str(alias / "restart.log"))
    monkeypatch.setattr(
        "application.runtime.restart_debug.tempfile.gettempdir",
        lambda: str(fallback),
    )

    write_restart_debug_log("bridge", "safe")

    assert not (external / "restart.log").exists()
    assert (fallback / "shinsekai-restart-debug.log").is_file()


def test_restart_debug_log_canonicalizes_the_platform_temp_alias(
    tmp_path,
    monkeypatch,
):
    external = tmp_path / "platform-temp"
    alias = tmp_path / "platform-temp-alias"
    external.mkdir()
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError):
        import pytest

        pytest.skip("directory symlinks are unavailable")
    monkeypatch.delenv("SHINSEKAI_RESTART_LOG", raising=False)
    monkeypatch.setattr(
        "application.runtime.restart_debug.tempfile.gettempdir",
        lambda: str(alias),
    )

    assert _restart_debug_log_path() == (
        external / "shinsekai-restart-debug.log"
    )

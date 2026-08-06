from __future__ import annotations

import json

import pytest

from core.runtime_env import pip_index as pip_index_config


@pytest.mark.parametrize(
    "args",
    [
        ["-i", "https://example.invalid/simple"],
        ["-ihttps://example.invalid/simple"],
        ["--index-url", "https://example.invalid/simple"],
        ["--index-url=https://example.invalid/simple"],
        ["--extra-index-url", "https://example.invalid/simple"],
        ["--extra-index-url=https://example.invalid/simple"],
        ["--no-index"],
        ["--retries", "2", "--extra-index-url", "https://example.invalid/simple"],
    ],
)
def test_has_explicit_pip_index_detects_index_intent(args):
    assert pip_index_config.has_explicit_pip_index(args) is True


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["requests>=2"],
        ["--retries", "2", "--trusted-host", "mirror.example"],
        ["--find-links", "./wheels"],
    ],
)
def test_has_explicit_pip_index_ignores_non_index_args(args):
    assert pip_index_config.has_explicit_pip_index(args) is False


def _clear_index_env(monkeypatch):
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_NO_INDEX",
        "PIP_CONFIG_FILE",
        "SHINSEKAI_PIP_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URLS",
        "SHINSEKAI_RUNTIME_SOURCE",
        "SHINSEKAI_MIRROR_REGION",
        "SHINSEKAI_RUNTIME_MANIFEST",
        "SHINSEKAI_SOURCE_ROOT",
        "SHINSEKAI_PROJECT_ROOT",
        "EASYAI_PROJECT_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "env_name",
    ["PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_NO_INDEX", "PIP_CONFIG_FILE"],
)
def test_pip_index_urls_respects_user_pip_env_overrides(monkeypatch, env_name):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv(env_name, "https://user.example/simple")

    assert pip_index_config.pip_index_urls() == []


def test_pip_index_urls_prefers_china_mirrors_by_default(monkeypatch):
    _clear_index_env(monkeypatch)

    urls = pip_index_config.pip_index_urls()

    assert urls[0] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://pypi.org/simple/" in urls


def test_pip_index_urls_uses_official_index_for_global_mirror_region(monkeypatch):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "global")

    assert pip_index_config.pip_index_urls() == ["https://pypi.org/simple/"]


def test_pip_index_urls_runtime_source_overrides_mirror_region(monkeypatch):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_MIRROR_REGION", "global")
    monkeypatch.setenv("SHINSEKAI_RUNTIME_SOURCE", "china")

    urls = pip_index_config.pip_index_urls()

    assert urls[0] == "https://pypi.tuna.tsinghua.edu.cn/simple/"
    assert "https://pypi.org/simple/" in urls


def test_runtime_manifest_is_read_from_packaged_source_root_not_project_or_cwd(
    tmp_path,
    monkeypatch,
):
    _clear_index_env(monkeypatch)
    source = tmp_path / "source"
    project = tmp_path / "project"
    cwd = tmp_path / "cwd"
    source.mkdir()
    project.mkdir()
    cwd.mkdir()

    def write_manifest(root, url):
        (root / "runtime_manifest.json").write_text(
            json.dumps(
                {
                    "pip_indexes": {
                        "official": url,
                        "china": url,
                    }
                }
            ),
            encoding="utf-8",
        )

    write_manifest(source, "https://source.example/simple/")
    write_manifest(project, "https://project.example/simple/")
    write_manifest(cwd, "https://cwd.example/simple/")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_PROJECT_ROOT", project.as_posix())
    monkeypatch.chdir(cwd)

    assert pip_index_config.pip_index_urls() == ["https://source.example/simple/"]


def test_relative_manifest_and_source_environment_paths_are_rejected(monkeypatch):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_RUNTIME_MANIFEST", "runtime_manifest.json")
    with pytest.raises(ValueError, match="SHINSEKAI_RUNTIME_MANIFEST"):
        pip_index_config.pip_index_urls()

    monkeypatch.delenv("SHINSEKAI_RUNTIME_MANIFEST")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", "relative-source")
    with pytest.raises(ValueError, match="SHINSEKAI_SOURCE_ROOT"):
        pip_index_config.pip_index_urls()


def test_runtime_manifest_environment_rejects_user_home_alias(monkeypatch):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_RUNTIME_MANIFEST", "~/runtime_manifest.json")

    with pytest.raises(ValueError, match="must be an absolute path"):
        pip_index_config.pip_index_urls()


def test_empty_runtime_manifest_environment_is_rejected_without_default_fallback(
    monkeypatch,
):
    _clear_index_env(monkeypatch)
    monkeypatch.setenv("SHINSEKAI_RUNTIME_MANIFEST", "")

    with pytest.raises(ValueError, match="SHINSEKAI_RUNTIME_MANIFEST"):
        pip_index_config.pip_index_urls()


def test_explicit_runtime_manifest_read_failure_does_not_fall_back(
    tmp_path,
    monkeypatch,
):
    _clear_index_env(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "runtime_manifest.json").write_text("{}", encoding="utf-8")
    missing = tmp_path / "missing-runtime-manifest.json"
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_RUNTIME_MANIFEST", missing.as_posix())

    with pytest.raises(RuntimeError, match="SHINSEKAI_RUNTIME_MANIFEST"):
        pip_index_config.pip_index_urls()


def test_explicit_runtime_manifest_invalid_json_does_not_fall_back(
    tmp_path,
    monkeypatch,
):
    _clear_index_env(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "runtime_manifest.json").write_text("{}", encoding="utf-8")
    invalid = tmp_path / "invalid-runtime-manifest.json"
    invalid.write_text("{", encoding="utf-8")
    monkeypatch.setenv("SHINSEKAI_SOURCE_ROOT", source.as_posix())
    monkeypatch.setenv("SHINSEKAI_RUNTIME_MANIFEST", invalid.as_posix())

    with pytest.raises(ValueError, match="not valid JSON"):
        pip_index_config.pip_index_urls()


def test_runtime_manifest_environment_rejects_absolute_lexical_alias(
    tmp_path,
    monkeypatch,
):
    _clear_index_env(monkeypatch)
    manifest = tmp_path / "runtime_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(
        "SHINSEKAI_RUNTIME_MANIFEST",
        f"{tmp_path.as_posix()}/./runtime_manifest.json",
    )

    with pytest.raises(ValueError, match="lexical path aliases"):
        pip_index_config.pip_index_urls()


def test_source_candidate_deduplication_does_not_follow_links(tmp_path):
    source = tmp_path / "source"
    alias = tmp_path / "source-alias"
    source.mkdir()
    try:
        alias.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    assert pip_index_config._unique_paths([alias, source]) == [alias, source]


@pytest.mark.parametrize(
    "line",
    [
        "-r sub-requirements.txt",
        "-rsub-requirements.txt",
        "--requirement sub-requirements.txt",
        "--requirement=sub-requirements.txt",
        "-c constraints.txt",
        "-cconstraints.txt",
        "--constraint constraints.txt",
        "--constraint=constraints.txt",
    ],
)
def test_requirements_lines_define_index_keeps_nested_requirement_intent(line):
    assert pip_index_config.requirements_lines_define_index([line]) is True

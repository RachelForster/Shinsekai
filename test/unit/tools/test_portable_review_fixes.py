"""Regression tests for PR #460 review fixes: tag binding, partial manifest merge, stale cleanup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.build_portable_bundle import build_portable_bundle
from scripts.portable.archive import compute_sha256
from scripts.portable.hub_providers import UploadTargetConfig, build_remote_url
from scripts.portable.models import bundle_huggingface_asset
from scripts.portable.plan_matrix import resolve_portable_plan
from scripts.portable.upload_artifacts import publish_portable_artifacts
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot

REPO_ROOT = Path(__file__).resolve().parents[3]


def _seed_minimal_runtime(runtime_dir: Path) -> None:
    py = runtime_dir / "python.exe"
    sp = runtime_dir / "Lib" / "site-packages" / "Pillow-1.0.0.dist-info"
    py.parent.mkdir(parents=True, exist_ok=True)
    sp.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"py")
    (sp / "METADATA").write_text("Metadata-Version: 2.1\nName: Pillow\nVersion: 1.0.0\n", encoding="utf-8")


def test_plan_matrix_binds_release_tags_and_semver_version_tags(tmp_path: Path) -> None:
    (tmp_path / "VERSION").write_text("2.7.0\n", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"version": "2.7.0"}), encoding="utf-8")

    ok_tag = resolve_portable_plan(
        source_root=tmp_path,
        event_name="push",
        ref_name="v2.7.0",
        github_ref="refs/tags/v2.7.0",
    )
    assert ok_tag["release_prefix"] == "v2.7.0"
    assert ok_tag["version"] == "2.7.0"

    ok_rc = resolve_portable_plan(
        source_root=tmp_path,
        event_name="push",
        ref_name="v2.7.0-rc.1",
        github_ref="refs/tags/v2.7.0-rc.1",
    )
    assert ok_rc["release_prefix"] == "v2.7.0-rc.1"

    with pytest.raises(ValueError, match="must match VERSION"):
        resolve_portable_plan(
            source_root=tmp_path,
            event_name="push",
            ref_name="v2.6.0",
            github_ref="refs/tags/v2.6.0",
        )

    for bad_tag in ("v2.7", "v2.7.0-beta.1"):
        with pytest.raises(ValueError, match="Invalid release tag"):
            resolve_portable_plan(
                source_root=tmp_path,
                event_name="push",
                ref_name=bad_tag,
                github_ref=f"refs/tags/{bad_tag}",
            )

    with pytest.raises(ValueError, match="must match VERSION"):
        resolve_portable_plan(
            source_root=tmp_path,
            event_name="workflow_dispatch",
            input_version_tag="v2.6.0",
        )

    assert (
        resolve_portable_plan(
            source_root=tmp_path,
            event_name="workflow_dispatch",
            input_version_tag="v2.7.0-rc.2",
        )["release_prefix"]
        == "v2.7.0-rc.2"
    )
    assert (
        resolve_portable_plan(
            source_root=tmp_path,
            event_name="workflow_dispatch",
            input_version_tag="nightly-20261124",
        )["release_prefix"]
        == "nightly-20261124"
    )

    with pytest.raises(ValueError, match="Unsafe version_tag"):
        resolve_portable_plan(
            source_root=tmp_path,
            event_name="workflow_dispatch",
            input_version_tag="../bad",
        )


def test_partial_republish_merges_remote_manifest_and_workflow_serializes_publish(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    linux_arc = stage / "Shinsekai-Portable-v2.7.0-linux-x64.tar.gz"
    linux_arc.write_bytes(b"new-linux-payload")
    linux_digest = compute_sha256(linux_arc)
    linux_arc.with_name(f"{linux_arc.name}.sha256").write_text(
        f"{linux_digest}  {linux_arc.name}\n",
        encoding="utf-8",
    )
    linux_arc.with_name(f"{linux_arc.name}.meta.json").write_text(
        json.dumps({"platform": "linux-x64", "sha256": linux_digest, "included_models": ["embedding"]}),
        encoding="utf-8",
    )

    existing_hf_manifest = json.dumps(
        {
            "version": "2.7.0",
            "release_prefix": "v2.7.0",
            "artifacts": [
                {
                    "platform": "windows-x64",
                    "archive_name": "Shinsekai-Portable-v2.7.0-windows-x64.zip",
                    "size_bytes": 1234,
                    "sha256": "a" * 64,
                    "included_models": ["embedding"],
                    "urls": {"huggingface": "https://huggingface.co/org/repo/resolve/main/v2.7.0/win.zip"},
                },
                {
                    "platform": "linux-x64",
                    "archive_name": "Shinsekai-Portable-v2.7.0-linux-x64.tar.gz",
                    "size_bytes": 999,
                    "sha256": "b" * 64,
                    "included_models": [],
                    "urls": {"huggingface": "https://huggingface.co/org/repo/resolve/main/v2.7.0/old.tar.gz"},
                },
            ],
        }
    )

    uploaded_files: dict[tuple[str, str], bytes] = {}

    def fake_upload(cfg: UploadTargetConfig, local_path: Path, remote_path: str, _msg: str) -> str:
        uploaded_files[(cfg.provider, remote_path)] = local_path.read_bytes()
        return build_remote_url(cfg, remote_path)

    def fake_fetch(cfg: UploadTargetConfig, remote_path: str) -> str | None:
        if cfg.provider == "huggingface" and remote_path == "v2.7.0/portable-manifest.json":
            return existing_hf_manifest
        return None

    targets = (
        UploadTargetConfig("huggingface", True, "hf-token", "org/shinsekai", "model"),
        UploadTargetConfig("modelscope", True, "ms-token", "org/shinsekai", "model"),
    )
    publish_portable_artifacts(
        targets=targets,
        release_prefix="v2.7.0",
        version="2.7.0",
        artifacts_dir=stage,
        upload_fn=fake_upload,
        fetch_fn=fake_fetch,
    )

    hf_manifest = json.loads(uploaded_files[("huggingface", "v2.7.0/portable-manifest.json")].decode("utf-8"))
    assert [entry["platform"] for entry in hf_manifest["artifacts"]] == ["windows-x64", "linux-x64"]
    assert hf_manifest["artifacts"][0]["sha256"] == "a" * 64
    assert hf_manifest["artifacts"][1]["sha256"] == linux_digest

    hf_sums = uploaded_files[("huggingface", "v2.7.0/SHA256SUMS.txt")].decode("utf-8").splitlines()
    assert hf_sums == [
        f"{'a' * 64}  Shinsekai-Portable-v2.7.0-windows-x64.zip",
        f"{linux_digest}  Shinsekai-Portable-v2.7.0-linux-x64.tar.gz",
    ]

    ms_manifest = json.loads(uploaded_files[("modelscope", "v2.7.0/portable-manifest.json")].decode("utf-8"))
    assert [entry["platform"] for entry in ms_manifest["artifacts"]] == ["linux-x64"]

    with pytest.raises(ValueError, match="invalid JSON"):
        publish_portable_artifacts(
            targets=(targets[0],),
            release_prefix="v2.7.0",
            version="2.7.0",
            artifacts_dir=stage,
            upload_fn=fake_upload,
            fetch_fn=lambda _cfg, _remote: "{not-json",
        )

    workflow_path = REPO_ROOT / ".github" / "workflows" / "portable-artifacts.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow_text)
    assert "scripts/portable/plan_matrix.py" in workflow_text
    assert parsed["jobs"]["publish"]["concurrency"] == {
        "group": "portable-publish-${{ needs.plan.outputs.release_prefix }}",
        "cancel-in-progress": False,
    }


def test_rebuild_cleans_stale_archives_and_upload_rejects_mismatched_sidecar(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "shinsekai.exe").write_bytes(b"win-bin")
    runtime_dir = tmp_path / "runtime"
    _seed_minimal_runtime(runtime_dir)
    frontend_dist = tmp_path / "frontend_dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    empty_data = tmp_path / "empty_data"
    out_dir = tmp_path / "dist" / "Shinsekai-Portable-v2.7.0-windows-x64"

    # 1) Initial ZIP build with sidecars
    build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=empty_data,
        output_dir=out_dir,
        target="windows-x64",
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist,
        models=(),
        archive=True,
        archive_format="zip",
        write_sha256=True,
        write_metadata=True,
        overwrite=True,
    )
    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    assert zip_path.is_file()
    assert zip_path.with_name(f"{zip_path.name}.sha256").is_file()
    assert zip_path.with_name(f"{zip_path.name}.meta.json").is_file()

    # 2) Format switch to tar.gz without sidecars cleans old .zip and its sidecars
    build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=empty_data,
        output_dir=out_dir,
        target="windows-x64",
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist,
        models=(),
        archive=True,
        archive_format="tar.gz",
        write_sha256=False,
        write_metadata=False,
        overwrite=True,
    )
    targz_path = out_dir.parent / f"{out_dir.name}.tar.gz"
    assert targz_path.is_file()
    assert not zip_path.exists()
    assert not zip_path.with_name(f"{zip_path.name}.sha256").exists()
    assert not zip_path.with_name(f"{zip_path.name}.meta.json").exists()

    # 3) Same-format rebuild without sidecars removes stale sidecars
    build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=empty_data,
        output_dir=out_dir,
        target="windows-x64",
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist,
        models=(),
        archive=True,
        archive_format="zip",
        write_sha256=True,
        write_metadata=True,
        overwrite=True,
    )
    assert zip_path.with_name(f"{zip_path.name}.sha256").is_file()
    build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=empty_data,
        output_dir=out_dir,
        target="windows-x64",
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist,
        models=(),
        archive=True,
        archive_format="zip",
        write_sha256=False,
        write_metadata=False,
        overwrite=True,
    )
    assert zip_path.is_file()
    assert not zip_path.with_name(f"{zip_path.name}.sha256").exists()
    assert not zip_path.with_name(f"{zip_path.name}.meta.json").exists()

    # 4) Upload refuses a mismatched/stale .sha256 sidecar
    zip_path.with_name(f"{zip_path.name}.sha256").write_text(f"{'0' * 64}  {zip_path.name}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        publish_portable_artifacts(
            targets=(UploadTargetConfig("huggingface", True, "hf-token", "org/shinsekai", "model"),),
            release_prefix="v2.7.0",
            version="2.7.0",
            artifacts_dir=out_dir.parent,
            upload_fn=lambda cfg, _p, r, _m: build_remote_url(cfg, r),
        )


def test_bundle_huggingface_asset_honors_target_cache_despite_frozen_hf_hub_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import huggingface_hub
    import huggingface_hub.constants

    stale_hub = tmp_path / "stale-repo-cache" / "huggingface" / "hub"
    stale_hub.mkdir(parents=True)
    monkeypatch.setattr(huggingface_hub.constants, "HF_HUB_CACHE", str(stale_hub))
    monkeypatch.setenv("SHINSEKAI_SKIP_NETWORK_REGION_PROBE", "1")
    monkeypatch.setattr(
        "config.mirror_env.apply_mirror_environment_from_system_config",
        lambda *_args, **_kwargs: None,
    )

    spec = ModelAssetSpec(
        asset_id="test.portable.hf",
        title="Portable test HF model",
        variant="default",
        repo_id="owner/portable-test-model",
        allow_patterns=("model.onnx", "tokens.txt"),
        required_file_groups=(("model.onnx",), ("tokens.txt",)),
        enforce_allow_patterns=False,
    )

    def fake_snapshot_download(repo_id: str, **kwargs):
        hub_root = Path(str(kwargs.get("cache_dir") or huggingface_hub.constants.HF_HUB_CACHE))
        repo_dir = hub_root / ("models--" + repo_id.replace("/", "--"))
        rev = "d" * 40
        snapshot_dir = repo_dir / "snapshots" / rev
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "model.onnx").write_bytes(b"onnx-weights")
        (snapshot_dir / "tokens.txt").write_text("0 <unk>\n", encoding="utf-8")
        (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
        (repo_dir / "refs" / "main").write_text(rev, encoding="utf-8")
        return str(snapshot_dir)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

    data_src = tmp_path / "data_src"
    output_dir = tmp_path / "bundle"
    warnings: list[str] = []
    ok = bundle_huggingface_asset(
        spec,
        label="测试模型",
        data_source_root=data_src,
        output_dir=output_dir,
        download_missing=True,
        warnings=warnings,
    )

    assert ok is True
    assert warnings == []
    assert list(stale_hub.iterdir()) == []
    target_hub = output_dir / "data" / "cache" / "huggingface" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(target_hub))
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(target_hub))
    monkeypatch.delenv("HF_HOME", raising=False)
    resolved = find_cached_huggingface_snapshot(spec)
    assert resolved is not None
    assert (resolved / "model.onnx").read_bytes() == b"onnx-weights"


def test_portable_workflow_uses_prefer_binary_for_embedded_pip_install() -> None:
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "portable-artifacts.yml").read_text(
        encoding="utf-8"
    )
    assert "pip install --prefer-binary -r requirements-runtime-core.txt" in workflow_text

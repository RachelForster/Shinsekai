"""Unit tests for cross-platform portable bundling, safe extraction, uploaders, and CI workflow."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest
import yaml

from ai.asr.sherpa_onnx_adapter import SHERPA_SENSEVOICE_ASSET, SHERPA_ZIPFORMER_ASSET
from ai.memory.config import EMBEDDING_MODEL_ASSET
from core.agent.pi_runtime import PI_ARCHIVES, PI_VERSION
from scripts.build_portable_bundle import build_portable_bundle, main as build_cli_main
from scripts.portable.archive import compute_sha256
from scripts.portable.gguf_runtime import bundle_perception_gguf, safe_extract_tar_gz, safe_extract_zip
from scripts.portable.hub_providers import UploadTargetConfig, build_remote_url
from scripts.portable.plan_matrix import CATALOG
from scripts.portable.targets import (
    PERCEPTION_GGUF_FILES,
    PLATFORM_TARGETS,
    QWEN3_TTS_GGUF_FILES,
    SUPPORTED_TARGETS,
    default_models_for_target,
    resolve_target,
)
from scripts.portable.upload_artifacts import main as upload_cli_main, publish_portable_artifacts

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_dist_info(site_packages: Path, name: str, version: str = "1.0.0") -> None:
    dist_info = site_packages / f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def _seed_runtime(runtime_dir: Path, *, os_family: str, packages: tuple[str, ...]) -> None:
    if os_family == "windows":
        py = runtime_dir / "python.exe"
        sp = runtime_dir / "Lib" / "site-packages"
    else:
        py = runtime_dir / "bin" / "python3.10"
        sp = runtime_dir / "lib" / "python3.10" / "site-packages"
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_bytes(b"python")
    for pkg in packages:
        _write_dist_info(sp, pkg)


def _seed_models(data_src: Path, *, llama_executable: str, pi_platform_key: str) -> object:
    hub = data_src / "data" / "cache" / "huggingface" / "hub"
    rev = "c" * 40
    for spec in (SHERPA_ZIPFORMER_ASSET, SHERPA_SENSEVOICE_ASSET):
        repo_dir = hub / ("models--" + spec.repo_id.replace("/", "--"))
        snap = repo_dir / "snapshots" / rev
        snap.mkdir(parents=True, exist_ok=True)
        (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
        (repo_dir / "refs" / "main").write_text(rev, encoding="utf-8")
        for group in spec.required_file_groups:
            (snap / group[0]).write_bytes(b"sherpa")

    emb_dir = hub / ("models--" + EMBEDDING_MODEL_ASSET.repo_id.replace("/", "--"))
    emb_snap = emb_dir / "snapshots" / rev
    (emb_snap / "onnx").mkdir(parents=True, exist_ok=True)
    (emb_dir / "refs").mkdir(parents=True, exist_ok=True)
    (emb_dir / "refs" / "main").write_text(rev, encoding="utf-8")
    (emb_snap / "config.json").write_text(
        '{"model_type": "bert", "hidden_size": 384, "vocab_size": 250037, "architectures": ["BertModel"]}',
        encoding="utf-8",
    )
    (emb_snap / "tokenizer_config.json").write_text(
        '{"model_max_length": 512, "tokenizer_class": "XLMRobertaTokenizer"}',
        encoding="utf-8",
    )
    (emb_snap / "tokenizer.json").write_text(
        '{"version": "1.0", "model": {"type": "Unigram", "vocab": [["[UNK]", 0.0], ["hello", -1.0]]}}',
        encoding="utf-8",
    )
    (emb_snap / "onnx" / "model_quantized.onnx").write_bytes(b"onnx")
    test_embedding_spec = replace(
        EMBEDDING_MODEL_ASSET,
        snapshot_validator=lambda snap: (snap / "onnx" / "model_quantized.onnx").is_file(),
    )

    gguf_dir = data_src / "data" / "models" / "perception-gguf"
    (gguf_dir / "llama.cpp").mkdir(parents=True, exist_ok=True)
    (gguf_dir / "llama.cpp" / llama_executable).write_bytes(b"llama-server")
    for name in PERCEPTION_GGUF_FILES:
        (gguf_dir / name).write_bytes(b"gguf-data")

    tts_dir = data_src / "data" / "models" / "qwen3-tts-gguf"
    tts_dir.mkdir(parents=True, exist_ok=True)
    for name in QWEN3_TTS_GGUF_FILES:
        (tts_dir / name).write_bytes(b"qwen3-tts-gguf")

    pi_inst = data_src / "data" / "agent" / "runtimes" / "pi" / f"{PI_VERSION}-{pi_platform_key}"
    pi_inst.mkdir(parents=True, exist_ok=True)
    pi_exe = "pi.exe" if pi_platform_key.startswith("windows-") else "pi"
    pi_data = b"pi-binary"
    (pi_inst / pi_exe).write_bytes(pi_data)
    (pi_inst / pi_exe).chmod(0o755)
    (pi_inst / "installed.json").write_text(
        json.dumps({"version": PI_VERSION, "platform": pi_platform_key, "archiveSha256": PI_ARCHIVES[pi_platform_key][1], "executable": pi_exe, "files": {pi_exe: hashlib.sha256(pi_data).hexdigest()}}),
        encoding="utf-8",
    )

    return test_embedding_spec


def test_target_resolution_aliases_and_windows_arm64_defaults() -> None:
    assert set(SUPPORTED_TARGETS) == {
        "windows-x64",
        "windows-arm64",
        "macos-arm64",
        "linux-x64",
        "linux-arm64",
    }
    assert resolve_target("win-x64").name == "windows-x64"
    assert resolve_target("darwin-arm64").uses_app_bundle is True
    assert "sherpa-asr" not in default_models_for_target("windows-arm64")
    assert "sherpa-asr" in default_models_for_target("linux-x64")
    with pytest.raises(ValueError, match="Unsupported portable target"):
        resolve_target("freebsd-x64")


def test_build_linux_x64_portable_targz_and_sidecars(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "shinsekai").write_bytes(b"linux-bin")
    runtime_dir = tmp_path / "runtime"
    _seed_runtime(runtime_dir, os_family="linux", packages=("onnxruntime", "huggingface-hub", "sherpa-onnx", "Pillow", "rapidocr-onnxruntime", "filelock"))
    frontend_dist = tmp_path / "frontend_dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<html></html>", encoding="utf-8")

    data_src = tmp_path / "data_src"
    emb_spec = _seed_models(data_src, llama_executable="llama-server", pi_platform_key="linux-x64")

    out_dir = tmp_path / "Shinsekai-Portable-v2.7.0-linux-x64"
    report = build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=data_src,
        output_dir=out_dir,
        target="linux-x64",
        runtime_dir=runtime_dir,
        frontend_dist_dir=frontend_dist,
        archive=True,
        write_sha256=True,
        write_metadata=True,
        embedding_asset=emb_spec,
    )

    assert report.target == "linux-x64"
    assert set(report.included_models) == {"embedding", "sherpa-asr", "perception-gguf", "qwen3-tts-gguf", "pi-agent"}
    assert report.archive_path is not None and report.archive_path.name.endswith(".tar.gz")
    assert report.sha256_path is not None and report.metadata_path is not None

    expected_digest = compute_sha256(report.archive_path)
    assert report.sha256_path.read_text(encoding="utf-8").strip() == f"{expected_digest}  {report.archive_path.name}"
    meta = json.loads(report.metadata_path.read_text(encoding="utf-8"))
    assert meta["platform"] == "linux-x64"
    assert meta["archive_format"] == "tar.gz"
    assert meta["sha256"] == expected_digest
    assert set(meta["included_models"]) == {"embedding", "sherpa-asr", "perception-gguf", "qwen3-tts-gguf", "pi-agent"}

    with tarfile.open(report.archive_path, "r:gz") as tf:
        names = set(tf.getnames())
    assert f"{out_dir.name}/.shinsekai-portable" in names
    assert f"{out_dir.name}/shinsekai" in names
    assert f"{out_dir.name}/data/models/perception-gguf/llama.cpp/llama-server" in names
    assert f"{out_dir.name}/data/models/qwen3-tts-gguf/{QWEN3_TTS_GGUF_FILES[0]}" in names
    assert f"{out_dir.name}/data/agent/runtimes/pi/{PI_VERSION}-linux-x64/pi" in names


def test_build_macos_arm64_app_bundle_layout(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    app_dir = release_dir / "bundle" / "macos" / "Shinsekai.app" / "Contents"
    (app_dir / "MacOS").mkdir(parents=True)
    (app_dir / "MacOS" / "shinsekai").write_bytes(b"macos-bin")
    (app_dir / "Resources" / "frontend" / "dist").mkdir(parents=True)
    (app_dir / "Resources" / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    (app_dir / "Resources" / "frontend_bridge.py").write_text("# bridge\n", encoding="utf-8")
    _seed_runtime(
        app_dir / "Resources" / "runtime",
        os_family="macos",
        packages=("onnxruntime", "huggingface-hub", "sherpa-onnx", "Pillow", "rapidocr-onnxruntime", "filelock"),
    )

    data_src = tmp_path / "data_src"
    emb_spec = _seed_models(data_src, llama_executable="llama-server", pi_platform_key="darwin-arm64")

    out_dir = tmp_path / "Shinsekai-Portable-v2.7.0-macos-arm64"
    report = build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=data_src,
        output_dir=out_dir,
        target="macos-arm64",
        archive=True,
        archive_format="tar.gz",
        write_sha256=True,
        write_metadata=True,
        embedding_asset=emb_spec,
    )

    assert set(report.included_models) == {"embedding", "sherpa-asr", "perception-gguf", "qwen3-tts-gguf", "pi-agent"}
    assert (out_dir / ".shinsekai-portable").is_file()
    assert (out_dir / "Shinsekai.app" / "Contents" / "MacOS" / "shinsekai").is_file()
    assert (out_dir / "data" / "models" / "perception-gguf" / "llama.cpp" / "llama-server").is_file()
    assert (out_dir / "data" / "models" / "qwen3-tts-gguf" / QWEN3_TTS_GGUF_FILES[0]).is_file()
    assert (out_dir / "data" / "agent" / "runtimes" / "pi" / f"{PI_VERSION}-darwin-arm64" / "pi").is_file()
    assert report.archive_path is not None
    with tarfile.open(report.archive_path, "r:gz") as tf:
        names = set(tf.getnames())
    assert f"{out_dir.name}/Shinsekai.app/Contents/MacOS/shinsekai" in names

    # Overriding runtime_dir and frontend_dist_dir onto an existing .app bundle replaces them cleanly.
    override_runtime = tmp_path / "override_runtime"
    _seed_runtime(
        override_runtime,
        os_family="macos",
        packages=("onnxruntime", "huggingface-hub", "sherpa-onnx", "Pillow", "rapidocr-onnxruntime", "filelock"),
    )
    override_frontend = tmp_path / "override_frontend"
    override_frontend.mkdir()
    (override_frontend / "index.html").write_text("<html>override</html>", encoding="utf-8")
    override_out = tmp_path / "Shinsekai-Portable-v2.7.0-macos-arm64-override"
    build_portable_bundle(
        source_root=REPO_ROOT,
        release_dir=release_dir,
        data_source_root=data_src,
        output_dir=override_out,
        target="macos-arm64",
        runtime_dir=override_runtime,
        frontend_dist_dir=override_frontend,
        embedding_asset=emb_spec,
    )
    assert (
        override_out / "Shinsekai.app" / "Contents" / "Resources" / "frontend" / "dist" / "index.html"
    ).read_text(encoding="utf-8") == "<html>override</html>"


def test_windows_zip_zero_models_and_strict_models_failure(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "shinsekai.exe").write_bytes(b"win-bin")
    runtime_dir = tmp_path / "runtime"
    _seed_runtime(runtime_dir, os_family="windows", packages=("Pillow",))
    frontend_dist = tmp_path / "frontend_dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    data_src = tmp_path / "empty_data"

    out_dir = tmp_path / "Shinsekai-Portable-v2.7.0-windows-x64"
    rc = build_cli_main(
        [
            "--target",
            "windows-x64",
            "--source-root",
            str(REPO_ROOT),
            "--release-dir",
            str(release_dir),
            "--runtime-dir",
            str(runtime_dir),
            "--frontend-dist-dir",
            str(frontend_dist),
            "--data-source-root",
            str(data_src),
            "--output-dir",
            str(out_dir),
            "--models",
            "none",
            "--archive",
            "--archive-format",
            "zip",
            "--write-sha256",
            "--write-metadata",
            "--overwrite",
        ]
    )
    assert rc == 0
    zip_path = tmp_path / "Shinsekai-Portable-v2.7.0-windows-x64.zip"
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
    assert f"{out_dir.name}/shinsekai.exe" in names
    assert not any(name.endswith(".gguf") for name in names)

    with pytest.raises(RuntimeError, match="Failed to include required portable model"):
        build_portable_bundle(
            source_root=REPO_ROOT,
            release_dir=release_dir,
            data_source_root=data_src,
            output_dir=tmp_path / "strict-fail",
            target="windows-x64",
            runtime_dir=runtime_dir,
            frontend_dist_dir=frontend_dist,
            models=("perception-gguf",),
            download_missing=False,
            strict_models=True,
        )


def test_safe_archive_extraction_rejects_traversal_and_downloads_gguf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../escape.txt", b"evil")
    with pytest.raises(ValueError, match="Unsafe path traversal"):
        safe_extract_zip(bad_zip, tmp_path / "out_zip")

    bad_tar = tmp_path / "bad.tar.gz"
    with tarfile.open(bad_tar, "w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../etc/passwd"
        tf.addfile(info)
    with pytest.raises(ValueError, match="escapes extraction directory"):
        safe_extract_tar_gz(bad_tar, tmp_path / "out_tar")

    def fake_download_archive(url: str, dest: Path, *_args: object, **_kwargs: object) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".tar.gz"):
            with tarfile.open(dest, "w:gz") as tf:
                payload = b"llama-server-bin"
                member = tarfile.TarInfo("build/bin/llama-server")
                member.size = len(payload)
                member.mode = 0o755
                tf.addfile(member, io.BytesIO(payload))
                lib_payload = b"libllama"
                lib_member = tarfile.TarInfo("build/bin/libllama.so")
                lib_member.size = len(lib_payload)
                tf.addfile(lib_member, io.BytesIO(lib_payload))
            return
        dest.write_bytes(b"gguf-bytes")

    monkeypatch.setattr("scripts.portable.gguf_runtime.download_archive", fake_download_archive)
    monkeypatch.setenv("HF_ENDPOINT", "https://example.invalid")
    # Force fallback HTTP download inside _download_gguf_weights by raising from hf_hub_download.
    monkeypatch.setattr(
        "huggingface_hub.hf_hub_download",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    warnings: list[str] = []
    bundle_out = tmp_path / "bundle"
    ok = bundle_perception_gguf(
        target=resolve_target("linux-x64"),
        data_source_root=tmp_path / "empty_src",
        output_dir=bundle_out,
        download_missing=True,
        llama_cpp_tag="b12669",
        warnings=warnings,
    )
    assert ok is True
    assert warnings == []
    assert (bundle_out / "data" / "models" / "perception-gguf" / "llama.cpp" / "llama-server").is_file()
    assert (bundle_out / "data" / "models" / "perception-gguf" / "llama.cpp" / "libllama.so").is_file()
    for name in PERCEPTION_GGUF_FILES:
        assert (bundle_out / "data" / "models" / "perception-gguf" / name).is_file()


def test_upload_artifacts_skips_when_placeholders_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("UPLOAD_HUGGINGFACE", "true")
    monkeypatch.setenv("UPLOAD_MODELSCOPE", "true")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_PORTABLE_REPO_ID", raising=False)
    monkeypatch.delenv("MODELSCOPE_TOKEN", raising=False)
    monkeypatch.delenv("MODELSCOPE_PORTABLE_REPO_ID", raising=False)

    assert upload_cli_main(["--release-prefix", "v2.7.0", "--version", "2.7.0"]) == 0
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "HF_TOKEN" in summary_text
    assert "MODELSCOPE_TOKEN" in summary_text
    assert "Skipped" in summary_text

    with pytest.raises(RuntimeError, match="No upload provider is configured"):
        publish_portable_artifacts(
            targets=(
                UploadTargetConfig("huggingface", True, "", ""),
                UploadTargetConfig("modelscope", True, "", ""),
            ),
            release_prefix="v2.7.0",
            version="2.7.0",
            require_configured=True,
        )


def test_upload_artifacts_publishes_to_hf_and_modelscope_and_cleans_temp_dirs(tmp_path: Path) -> None:
    archive_file = tmp_path / "Shinsekai-Portable-v2.7.0-linux-x64.tar.gz"
    archive_file.write_bytes(b"tar-gz-bytes")
    digest = compute_sha256(archive_file)
    archive_file.with_name(f"{archive_file.name}.sha256").write_text(
        f"{digest}  {archive_file.name}\n",
        encoding="utf-8",
    )
    archive_file.with_name(f"{archive_file.name}.meta.json").write_text(
        json.dumps(
            {
                "platform": "linux-x64",
                "sha256": digest,
                "included_models": ["embedding", "sherpa-asr"],
            }
        ),
        encoding="utf-8",
    )

    uploaded_calls: list[tuple[str, str, str, bytes]] = []

    def fake_upload(cfg: UploadTargetConfig, local_path: Path, remote_path: str, _msg: str) -> str:
        uploaded_calls.append((cfg.provider, cfg.repo_id, remote_path, local_path.read_bytes()))
        return build_remote_url(cfg, remote_path)

    seen_temp_dirs: list[Path] = []

    def fake_download(_run_id: str, _repo: str, platform: str, dest_dir: Path) -> None:
        seen_temp_dirs.append(dest_dir)
        target_arc = dest_dir / f"Shinsekai-Portable-v2.7.0-{platform}.tar.gz"
        target_arc.write_bytes(b"archive-" + platform.encode("utf-8"))

    targets = (
        UploadTargetConfig("huggingface", True, "hf-secret", "org/shinsekai", "dataset"),
        UploadTargetConfig("modelscope", True, "ms-secret", "org/shinsekai", "model"),
    )
    summary_path = tmp_path / "summary.md"
    report = publish_portable_artifacts(
        targets=targets,
        release_prefix="v2.7.0",
        version="2.7.0",
        github_run_id="12345",
        github_repo="RachelForster/Shinsekai",
        platforms=("linux-x64", "macos-arm64"),
        summary_path=summary_path,
        upload_fn=fake_upload,
        download_fn=fake_download,
    )

    assert report.uploaded_providers == ("huggingface", "modelscope")
    assert len(report.artifacts) == 2
    assert all(not temp_dir.exists() for temp_dir in seen_temp_dirs)
    remote_paths = [call[2] for call in uploaded_calls]
    assert "v2.7.0/Shinsekai-Portable-v2.7.0-linux-x64.tar.gz" in remote_paths
    assert "v2.7.0/Shinsekai-Portable-v2.7.0-macos-arm64.tar.gz.sha256" in remote_paths
    assert "v2.7.0/SHA256SUMS.txt" in remote_paths
    assert "v2.7.0/portable-manifest.json" in remote_paths
    assert "huggingface.co/datasets/org/shinsekai/resolve/main/v2.7.0/portable-manifest.json" in report.manifest_urls["huggingface"]
    assert "modelscope.cn/models/org/shinsekai/resolve/master/v2.7.0/portable-manifest.json" in report.manifest_urls["modelscope"]
    assert "[download]" in summary_path.read_text(encoding="utf-8")


def test_portable_artifacts_workflow_contract() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "portable-artifacts.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow_text)

    assert parsed["name"] == "Portable Artifacts"
    assert "workflow_dispatch" in parsed[True]
    assert parsed[True]["push"]["tags"] == ["v*"]

    runtime_sources = json.loads(
        (REPO_ROOT / "frontend" / "src-tauri" / "runtime_sources.json").read_text(encoding="utf-8")
    )
    for target in runtime_sources["targets"]:
        assert target in workflow_text

    rust_toolchain = (REPO_ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
    assert 'channel = "1.96.0"' in rust_toolchain
    assert "dtolnay/rust-toolchain@1.96.0" in workflow_text
    assert "actions/upload-artifact@v4" in workflow_text
    assert "qwen3-tts-gguf" in workflow_text
    assert "pi-agent" in workflow_text
    for platform_name, target_cfg in PLATFORM_TARGETS.items():
        assert CATALOG[platform_name]["default_models"] == ",".join(target_cfg.default_models)
        assert "qwen3-tts-gguf" in target_cfg.default_models and "pi-agent" in target_cfg.default_models

    for placeholder in (
        "secrets.HF_TOKEN",
        "secrets.MODELSCOPE_TOKEN",
        "vars.HF_PORTABLE_REPO_ID",
        "vars.HF_PORTABLE_REPO_TYPE",
        "vars.MODELSCOPE_PORTABLE_REPO_ID",
        "vars.MODELSCOPE_PORTABLE_REPO_TYPE",
        "vars.SHINSEKAI_LLAMA_CPP_TAG",
    ):
        assert placeholder in workflow_text

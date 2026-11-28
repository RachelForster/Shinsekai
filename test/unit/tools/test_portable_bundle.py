"""Tests for portable model path resolution, lazy GGUF server imports, and bundle builder."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from ai.asr.sherpa_onnx_adapter import SHERPA_SENSEVOICE_ASSET, SHERPA_ZIPFORMER_ASSET
from ai.memory.config import EMBEDDING_MODEL_ASSET
from application.characters.sprite import mouth_resources
from application.perception import server_launcher
from config.tts_provider_config import QWEN3_TTS_GGUF_DEFAULT_URL
from core.agent.pi_runtime import PI_ARCHIVES, PI_VERSION
from core.media import toonout_assets
from core.model_assets.service import find_cached_huggingface_snapshot
from scripts.build_portable_bundle import audit_portable_bundle, build_portable_bundle
from scripts.portable.targets import QWEN3_TTS_GGUF_FILES, resolve_target


def _seed_fake_hf_sherpa_asr(root: Path) -> None:
    hub = root / "data" / "cache" / "huggingface" / "hub"
    rev = "b" * 40
    for spec in (SHERPA_ZIPFORMER_ASSET, SHERPA_SENSEVOICE_ASSET):
        repo_dir = hub / ("models--" + spec.repo_id.replace("/", "--"))
        snap = repo_dir / "snapshots" / rev
        snap.mkdir(parents=True, exist_ok=True)
        (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
        (repo_dir / "refs" / "main").write_text(rev, encoding="utf-8")
        for group in spec.required_file_groups:
            (snap / group[0]).write_bytes(b"fake-sherpa-onnx")


def _seed_fake_hf_embedding(root: Path) -> None:
    repo_folder = "models--" + EMBEDDING_MODEL_ASSET.repo_id.replace("/", "--")
    rev = "a" * 40
    repo_dir = root / "data" / "cache" / "huggingface" / "hub" / repo_folder
    snap = repo_dir / "snapshots" / rev
    (snap / "onnx").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / "main").write_text(rev, encoding="utf-8")
    (snap / "config.json").write_text(
        '{"model_type": "bert", "hidden_size": 384, "vocab_size": 250037, "architectures": ["BertModel"]}',
        encoding="utf-8",
    )
    (snap / "tokenizer_config.json").write_text(
        '{"model_max_length": 512, "tokenizer_class": "XLMRobertaTokenizer"}',
        encoding="utf-8",
    )
    (snap / "tokenizer.json").write_text(
        '{"version": "1.0", "model": {"type": "Unigram", "vocab": [["[UNK]", 0.0], ["hello", -1.0]]}}',
        encoding="utf-8",
    )
    (snap / "onnx" / "model_quantized.onnx").write_bytes(b"fake-onnx-model")
    # Also create bulky xet dir that must NOT be copied
    xet_dir = root / "data" / "cache" / "huggingface" / "xet"
    xet_dir.mkdir(parents=True, exist_ok=True)
    (xet_dir / "chunk.bin").write_bytes(b"temp-xet-data")


def test_gguf_arguments_prefers_unified_data_models_over_legacy_cache(tmp_path: Path) -> None:
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    legacy = tmp_path / "data" / "cache" / "perception-gguf"
    unified = tmp_path / "data" / "models" / "perception-gguf"
    for folder in (legacy, unified):
        (folder / "llama.cpp").mkdir(parents=True, exist_ok=True)
        (folder / "llama.cpp" / exe).write_bytes(b"bin")
        (folder / "Qwen3VL-2B-Instruct-Q4_K_M.gguf").write_bytes(b"gguf")
        (folder / "mmproj-Qwen3VL-2B-Instruct-F16.gguf").write_bytes(b"mmproj")

    args = server_launcher._gguf_arguments(tmp_path)
    assert args[0] == "--gguf"
    assert Path(args[1]).parent.parent == unified


def test_perception_local_server_help_imports_without_torch(tmp_path: Path) -> None:
    # Block torch/transformers via empty site isolation (-S) or check bundled runtime if available
    repo_root = Path(__file__).resolve().parents[3]
    bundled_py = repo_root / "runtime" / "python.exe"
    python_exe = str(bundled_py) if bundled_py.is_file() else sys.executable
    proc = subprocess.run(
        [python_exe, str(repo_root / "tools" / "perception_local_server.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "--gguf" in proc.stdout


def test_build_portable_bundle_sanitizes_and_organizes_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    release_dir = tmp_path / "release"
    (release_dir / "runtime").mkdir(parents=True)
    (release_dir / "runtime" / "python.exe").write_bytes(b"py")
    (release_dir / "shinsekai.exe").write_bytes(b"exe")
    (release_dir / "frontend" / "dist").mkdir(parents=True)
    (release_dir / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")

    data_src = tmp_path / "data_src"
    _seed_fake_hf_embedding(data_src)
    _seed_fake_hf_sherpa_asr(data_src)
    test_embedding_spec = replace(
        EMBEDDING_MODEL_ASSET,
        snapshot_validator=lambda snap: (snap / "onnx" / "model_quantized.onnx").is_file(),
    )
    monkeypatch.setattr("scripts.build_portable_bundle.EMBEDDING_MODEL_ASSET", test_embedding_spec)

    # Seed legacy perception-gguf
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    gguf_dir = data_src / "data" / "cache" / "perception-gguf"
    (gguf_dir / "llama.cpp").mkdir(parents=True)
    (gguf_dir / "llama.cpp" / exe).write_bytes(b"llama")
    (gguf_dir / "Qwen3VL-2B-Instruct-Q4_K_M.gguf").write_bytes(b"q4")
    (gguf_dir / "mmproj-Qwen3VL-2B-Instruct-F16.gguf").write_bytes(b"mmproj")

    # Seed legacy ToonOut with machine-specific runtime.json & worker.log
    toon_dir = data_src / "cache" / "models" / "toonout"
    (toon_dir / "deps" / "timm").mkdir(parents=True)
    (toon_dir / "deps" / "timm" / "__init__.py").write_text("", encoding="utf-8")
    (toon_dir / "runtime.json").write_text('{"python": "C:/Users/secret/python.exe"}', encoding="utf-8")
    (toon_dir / "worker.log").write_text("old log", encoding="utf-8")
    fake_artifacts = {}
    for name in ("birefnet_finetuned_toonout.pth", "birefnet.py", "BiRefNet_config.py"):
        content = f"content-{name}".encode()
        (toon_dir / name).write_bytes(content)
        fake_artifacts[name] = (f"repo/{name}", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(toonout_assets, "ARTIFACTS", fake_artifacts)
    monkeypatch.setattr("scripts.build_portable_bundle.TOONOUT_ARTIFACTS", fake_artifacts)

    # Seed sprite-mouth models + packages
    mouth_dir = data_src / "data" / "models" / "sprite-mouth"
    mouth_dir.mkdir(parents=True)
    fake_mouth = {}
    for key in ("yolov3", "hrnetv2"):
        content = f"mouth-{key}".encode()
        (mouth_dir / f"{key}.safetensors").write_bytes(content)
        fake_mouth[key] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr(mouth_resources, "MODEL_FILES", fake_mouth)
    monkeypatch.setattr("scripts.build_portable_bundle.MOUTH_MODEL_FILES", fake_mouth)
    (data_src / "data" / "runtime" / "sprite-mouth" / "packages" / "python-3.13").mkdir(parents=True)
    (data_src / "data" / "runtime" / "sprite-mouth" / "packages" / "python-3.13" / "pkg.py").write_text("", encoding="utf-8")

    # Seed local qwen3-tts-gguf weights (sharing llama.cpp from perception-gguf)
    qwen3_dir = data_src / "data" / "models" / "qwen3-tts-gguf"
    qwen3_dir.mkdir(parents=True)
    for name in QWEN3_TTS_GGUF_FILES:
        (qwen3_dir / name).write_bytes(b"qwen3-gguf")

    # Seed verified Pi Agent runtime + decoy transient files that must not be bundled
    target_cfg = resolve_target("windows-x64")
    pi_key = target_cfg.pi_platform_key
    pi_root = data_src / "data" / "agent" / "runtimes" / "pi"
    pi_inst = pi_root / f"{PI_VERSION}-{pi_key}"
    pi_inst.mkdir(parents=True)
    pi_exe_name = "pi.exe" if target_cfg.os_family == "windows" else "pi"
    pi_exe = pi_inst / pi_exe_name
    pi_bytes = b"fake-pi-bin"
    pi_exe.write_bytes(pi_bytes)
    if os.name != "nt":
        pi_exe.chmod(0o755)
    (pi_inst / "installed.json").write_text(
        json.dumps(
            {
                "version": PI_VERSION,
                "platform": pi_key,
                "archiveSha256": PI_ARCHIVES[pi_key][1],
                "executable": pi_exe_name,
                "files": {pi_exe_name: hashlib.sha256(pi_bytes).hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    (pi_root / "downloads").mkdir(parents=True)
    (pi_root / "downloads" / PI_ARCHIVES[pi_key][0]).write_bytes(b"stale-zip")
    (data_src / "data" / "agent" / "pi-sessions").mkdir(parents=True)
    (data_src / "data" / "agent" / "agent.sqlite").write_bytes(b"sqlite")

    # Seed personal files that must NEVER leak into the bundle
    (data_src / "data" / "config").mkdir(parents=True, exist_ok=True)
    (data_src / "data" / "config" / "api.yaml").write_text("llm_api_key:\n  Deepseek: sk-secret1234567890", encoding="utf-8")
    (data_src / "data" / "shinsekai.db").write_bytes(b"sqlite")
    (data_src / "data" / "tts_bundles").mkdir(parents=True)
    (data_src / "data" / "models" / "gpt-sovits").mkdir(parents=True)

    output_dir = tmp_path / "Shinsekai-Portable-v2.7.0-win-x64"
    report = build_portable_bundle(
        source_root=repo_root,
        release_dir=release_dir,
        data_source_root=data_src,
        output_dir=output_dir,
        runtime_dir=release_dir / "runtime",
        frontend_dist_dir=release_dir / "frontend" / "dist",
    )

    assert set(report.included_models) == {
        "embedding",
        "sherpa-asr",
        "perception-gguf",
        "qwen3-tts-gguf",
        "pi-agent",
    }
    assert (output_dir / ".shinsekai-portable").is_file()
    assert not (output_dir / "一键启动Shinsekai.bat").exists()
    assert (output_dir / "使用说明.txt").is_file()
    assert (output_dir / "data" / "models" / "perception-gguf" / "Qwen3VL-2B-Instruct-Q4_K_M.gguf").is_file()
    assert (output_dir / "data" / "models" / "qwen3-tts-gguf" / QWEN3_TTS_GGUF_FILES[0]).is_file()
    assert not (output_dir / "data" / "models" / "qwen3-tts-gguf" / "llama.cpp").exists()
    assert (output_dir / "data" / "agent" / "runtimes" / "pi" / f"{PI_VERSION}-{pi_key}" / pi_exe_name).is_file()
    assert not (output_dir / "data" / "agent" / "runtimes" / "pi" / "downloads").exists()
    assert not (output_dir / "data" / "agent" / "agent.sqlite").exists()
    assert not (output_dir / "data" / "agent" / "pi-sessions").exists()
    assert not (output_dir / "data" / "models" / "toonout").exists()
    assert not (output_dir / "data" / "models" / "sprite-mouth").exists()
    assert not (output_dir / "data" / "cache" / "huggingface" / "xet").exists()

    bundled_api = yaml.safe_load((output_dir / "data" / "config" / "api.yaml").read_text(encoding="utf-8"))
    assert bundled_api["tts_provider"] == "qwen3-tts-gguf"
    assert bundled_api["gpt_sovits_url"] == QWEN3_TTS_GGUF_DEFAULT_URL

    monkeypatch.setenv("HF_HUB_CACHE", str(output_dir / "data" / "cache" / "huggingface" / "hub"))
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(output_dir / "data" / "cache" / "huggingface" / "hub"))
    monkeypatch.delenv("HF_HOME", raising=False)
    assert find_cached_huggingface_snapshot(test_embedding_spec) is not None
    assert find_cached_huggingface_snapshot(SHERPA_ZIPFORMER_ASSET) is not None
    assert find_cached_huggingface_snapshot(SHERPA_SENSEVOICE_ASSET) is not None

    # Audit rejects corrupted Pi runtime and dangling qwen3-tts-gguf config
    pi_out_exe = output_dir / "data" / "agent" / "runtimes" / "pi" / f"{PI_VERSION}-{pi_key}" / pi_exe_name
    pi_out_exe.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="pi-agent"):
        audit_portable_bundle(output_dir)
    pi_out_exe.write_bytes(pi_bytes)

    (output_dir / "data" / "models" / "qwen3-tts-gguf" / QWEN3_TTS_GGUF_FILES[1]).unlink()
    with pytest.raises(ValueError, match="qwen3-tts-gguf"):
        audit_portable_bundle(output_dir)
    (output_dir / "data" / "models" / "qwen3-tts-gguf" / QWEN3_TTS_GGUF_FILES[1]).write_bytes(b"qwen3-gguf")

    # Audit rejects leaked secrets
    (output_dir / "data" / "config" / "api.yaml").write_text(
        "llm_api_key:\n  Deepseek: sk-leak1234567890abcdef\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="llm_api_key"):
        audit_portable_bundle(output_dir)


def _write_fake_dist_info(site_packages: Path, name: str, version: str = "1.0.0") -> None:
    dist_info = site_packages / f"{name.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def test_optional_toonout_and_sprite_mouth_require_runnable_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    release_dir = tmp_path / "release"
    (release_dir / "runtime").mkdir(parents=True)
    (release_dir / "runtime" / "python.exe").write_bytes(b"py")
    (release_dir / "shinsekai.exe").write_bytes(b"exe")
    (release_dir / "frontend" / "dist").mkdir(parents=True)
    (release_dir / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")

    data_src = tmp_path / "data_src"
    toon_dir = data_src / "data" / "models" / "toonout"
    for extra in ("timm", "kornia", "einops"):
        (toon_dir / "deps" / extra).mkdir(parents=True, exist_ok=True)
        (toon_dir / "deps" / extra / "__init__.py").write_text("", encoding="utf-8")
    fake_artifacts = {}
    for name in ("birefnet_finetuned_toonout.pth", "birefnet.py", "BiRefNet_config.py"):
        content = f"content-{name}".encode()
        (toon_dir / name).write_bytes(content)
        fake_artifacts[name] = (f"repo/{name}", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(toonout_assets, "ARTIFACTS", fake_artifacts)
    monkeypatch.setattr("scripts.build_portable_bundle.TOONOUT_ARTIFACTS", fake_artifacts)

    mouth_dir = data_src / "data" / "models" / "sprite-mouth"
    mouth_dir.mkdir(parents=True)
    fake_mouth = {}
    for key in ("yolov3", "hrnetv2"):
        content = f"mouth-{key}".encode()
        (mouth_dir / f"{key}.safetensors").write_bytes(content)
        fake_mouth[key] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr(mouth_resources, "MODEL_FILES", fake_mouth)
    monkeypatch.setattr("scripts.build_portable_bundle.MOUTH_MODEL_FILES", fake_mouth)

    # 1) Without PyTorch / Python >= 3.12 runtimes, both optional packs are skipped cleanly
    unrunnable_out = tmp_path / "unrunnable-out"
    monkeypatch.setattr(
        mouth_resources,
        "_probe",
        lambda *_a, **_kw: {"version": [3, 10, 20], "missing": list(mouth_resources.MODULES)},
    )
    report = build_portable_bundle(
        source_root=repo_root,
        release_dir=release_dir,
        data_source_root=data_src,
        output_dir=unrunnable_out,
        runtime_dir=release_dir / "runtime",
        frontend_dist_dir=release_dir / "frontend" / "dist",
        models=("toonout", "sprite-mouth"),
    )
    assert report.included_models == ()
    assert len(report.warnings) == 2
    assert not (unrunnable_out / "data" / "models" / "toonout").exists()
    assert not (unrunnable_out / "data" / "models" / "sprite-mouth").exists()

    # Audit rejects manually dropped unrunnable ToonOut assets
    (unrunnable_out / "data" / "models" / "toonout").mkdir(parents=True)
    (unrunnable_out / "data" / "models" / "toonout" / "birefnet_finetuned_toonout.pth").write_bytes(b"x")
    with pytest.raises(ValueError, match="ToonOut"):
        audit_portable_bundle(unrunnable_out)

    # 2) When self-contained portable runtimes ARE provided, both bundle and pass audit
    toon_sp = data_src / "data" / "runtime" / "toonout" / "Lib" / "site-packages"
    (data_src / "data" / "runtime" / "toonout" / "python.exe").parent.mkdir(parents=True, exist_ok=True)
    (data_src / "data" / "runtime" / "toonout" / "python.exe").write_bytes(b"py")
    for pkg in ("torch", "torchvision", "transformers", "Pillow"):
        _write_fake_dist_info(toon_sp, pkg, "2.7.0")

    mouth_py = data_src / "data" / "runtime" / "sprite-mouth" / "python" / "python.exe"
    mouth_py.parent.mkdir(parents=True, exist_ok=True)
    mouth_py.write_bytes(b"py312")
    monkeypatch.setattr(
        mouth_resources,
        "_probe",
        lambda py, *_a, **_kw: (
            {"version": [3, 12, 8], "missing": []}
            if "sprite-mouth" in str(py)
            else {"version": [3, 10, 20], "missing": list(mouth_resources.MODULES)}
        ),
    )

    runnable_out = tmp_path / "runnable-out"
    report_ok = build_portable_bundle(
        source_root=repo_root,
        release_dir=release_dir,
        data_source_root=data_src,
        output_dir=runnable_out,
        runtime_dir=release_dir / "runtime",
        frontend_dist_dir=release_dir / "frontend" / "dist",
        models=("toonout", "sprite-mouth"),
    )
    assert set(report_ok.included_models) == {"toonout", "sprite-mouth"}
    assert report_ok.warnings == ()


def test_inspect_perception_setup_gguf_does_not_require_pytorch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.perception.models import GGUF_MODEL_ID

    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    gguf_dir = tmp_path / "data" / "models" / "perception-gguf"
    (gguf_dir / "llama.cpp").mkdir(parents=True)
    (gguf_dir / "llama.cpp" / exe).write_bytes(b"llama")
    (gguf_dir / "Qwen3VL-2B-Instruct-Q4_K_M.gguf").write_bytes(b"q4")
    (gguf_dir / "mmproj-Qwen3VL-2B-Instruct-F16.gguf").write_bytes(b"mmproj")

    py_dir = tmp_path / "runtime"
    py_exe = py_dir / ("python.exe" if os.name == "nt" else "bin/python3")
    py_exe.parent.mkdir(parents=True, exist_ok=True)
    py_exe.write_bytes(b"py")
    sp = py_dir / "Lib" / "site-packages"
    _write_fake_dist_info(sp, "Pillow", "11.0.0")
    _write_fake_dist_info(sp, "rapidocr-onnxruntime", "1.4.4")

    monkeypatch.setattr(
        server_launcher,
        "perception_dependency_issues",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("PyTorch check must not run for GGUF")),
    )

    ready = server_launcher.inspect_perception_setup(
        model=GGUF_MODEL_ID,
        python_path=str(py_exe),
        project_root=tmp_path,
        app_root=tmp_path,
    )
    assert ready["status"] == "ready"
    assert ready["modelCached"] is True

    import platform

    if not (sys.platform == "win32" and platform.machine().strip().upper() == "ARM64"):
        pillow_only_dir = tmp_path / "pillow-only-runtime"
        pillow_only_exe = pillow_only_dir / ("python.exe" if os.name == "nt" else "bin/python3")
        pillow_only_exe.parent.mkdir(parents=True, exist_ok=True)
        pillow_only_exe.write_bytes(b"py")
        _write_fake_dist_info(pillow_only_dir / "Lib" / "site-packages", "Pillow", "11.0.0")
        missing_ocr = server_launcher.inspect_perception_setup(
            model=GGUF_MODEL_ID,
            python_path=str(pillow_only_exe),
            project_root=tmp_path,
            app_root=tmp_path,
        )
        assert missing_ocr["status"] == "missing_dependency"
        assert missing_ocr["moduleName"] == "perception_gguf"
        assert missing_ocr["packageName"] == "rapidocr-onnxruntime"

    # If Pillow itself is missing, GGUF setup requests lightweight perception_gguf, never perception (PyTorch)
    bare_dir = tmp_path / "bare-runtime"
    bare_exe = bare_dir / ("python.exe" if os.name == "nt" else "bin/python3")
    bare_exe.parent.mkdir(parents=True, exist_ok=True)
    bare_exe.write_bytes(b"py")
    (bare_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)

    missing = server_launcher.inspect_perception_setup(
        model=GGUF_MODEL_ID,
        python_path=str(bare_exe),
        project_root=tmp_path,
        app_root=tmp_path,
    )
    assert missing["status"] == "missing_dependency"
    assert missing["moduleName"] == "perception_gguf"
    assert missing["packageName"].lower() == "pillow"


def test_unix_launchers_are_executable_and_prioritize_venv() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    unix_scripts = (
        "scripts/install.sh",
        "scripts/install.command",
        "scripts/start.sh",
        "scripts/start.command",
        "scripts/install-linux.sh",
        "scripts/start-linux.sh",
    )
    for rel in unix_scripts:
        script_path = repo_root / rel
        assert script_path.is_file(), f"Missing {rel}"

    start_sh = (repo_root / "scripts" / "start.sh").read_text(encoding="utf-8")
    install_sh = (repo_root / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert '".venv/bin/python"' in start_sh
    assert '".venv/bin/python"' in install_sh
    assert start_sh.index('".venv/bin/python"') < start_sh.index('CONDA_CMD="$(find_conda)"')
    assert install_sh.index('".venv/bin/python"') < install_sh.index('CONDA_CMD="$(find_conda)"')

    if (repo_root / ".git").exists():
        proc = subprocess.run(
            ["git", "ls-files", "-s", *unix_scripts],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        modes = {}
        for line in proc.stdout.strip().splitlines():
            mode, _sha, _stage_and_path = line.split(" ", 2)
            path = _stage_and_path.split("\t", 1)[1]
            modes[path] = mode
        assert modes == {rel: "100755" for rel in unix_scripts}

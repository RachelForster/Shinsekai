"""Tests for portable model path resolution, lazy GGUF server imports, and bundle builder."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ai.asr.sherpa_onnx_adapter import SHERPA_SENSEVOICE_ASSET, SHERPA_ZIPFORMER_ASSET
from ai.memory.config import EMBEDDING_MODEL_ASSET
from application.characters.sprite import mouth_resources
from application.perception import server_launcher
from core.media import toonout_assets
from core.model_assets.service import find_cached_huggingface_snapshot
from scripts.build_portable_bundle import audit_portable_bundle, build_portable_bundle


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
        "toonout",
        "sprite-mouth",
    }
    assert (output_dir / ".shinsekai-portable").is_file()
    assert not (output_dir / "一键启动Shinsekai.bat").exists()
    assert (output_dir / "使用说明.txt").is_file()
    assert (output_dir / "data" / "models" / "perception-gguf" / "Qwen3VL-2B-Instruct-Q4_K_M.gguf").is_file()
    assert (output_dir / "data" / "models" / "toonout" / "deps" / "timm" / "__init__.py").is_file()
    assert not (output_dir / "data" / "models" / "toonout" / "runtime.json").exists()
    assert not (output_dir / "data" / "models" / "toonout" / "worker.log").exists()
    assert not (output_dir / "data" / "cache" / "huggingface" / "xet").exists()

    monkeypatch.setenv("HF_HUB_CACHE", str(output_dir / "data" / "cache" / "huggingface" / "hub"))
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(output_dir / "data" / "cache" / "huggingface" / "hub"))
    monkeypatch.delenv("HF_HOME", raising=False)
    assert find_cached_huggingface_snapshot(test_embedding_spec) is not None
    assert find_cached_huggingface_snapshot(SHERPA_ZIPFORMER_ASSET) is not None
    assert find_cached_huggingface_snapshot(SHERPA_SENSEVOICE_ASSET) is not None

    # Audit rejects leaked secrets
    (output_dir / "data" / "config" / "api.yaml").write_text(
        "llm_api_key:\n  Deepseek: sk-leak1234567890abcdef\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="llm_api_key"):
        audit_portable_bundle(output_dir)

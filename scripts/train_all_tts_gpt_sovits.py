from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
GPT_ROOT = (
    ROOT
    / "data"
    / "tts_bundles"
    / "installed"
    / "gpt_sovits_v2pro"
    / "GPT-SoVITS-v2pro-20250604"
)
RUNTIME_PY = GPT_ROOT / "runtime" / "python.exe"
MANIFEST_PATH = ROOT / "data" / "tts_training" / "training_manifest.yaml"
CHARS_PATH = ROOT / "data" / "config" / "characters.yaml"
VERSION = "v2Pro"
PRETRAINED_S2D = GPT_ROOT / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Dv2Pro.pth"
PRETRAINED_S2G = GPT_ROOT / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2Pro.pth"
S2_CONFIG = GPT_ROOT / "GPT_SoVITS" / "configs" / "s2v2Pro.json"
S1_CONFIG = GPT_ROOT / "GPT_SoVITS" / "configs" / "s1longer-v2.yaml"
BERT_DIR = GPT_ROOT / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large"
CNHUBERT_DIR = GPT_ROOT / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base"
SV_PATH = GPT_ROOT / "GPT_SoVITS" / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt"


def _as_posix(path: Path | str) -> str:
    return Path(path).resolve().as_posix()


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if data is None else data


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _run_python(script: str, env_updates: dict[str, str], extra_args: list[str] | None = None) -> None:
    env = os.environ.copy()
    env.update(env_updates)
    env["TEMP"] = str(GPT_ROOT / "TEMP")
    env["TMP"] = str(GPT_ROOT / "TEMP")
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    (GPT_ROOT / "TEMP").mkdir(parents=True, exist_ok=True)
    cmd = [str(RUNTIME_PY), "-s", script]
    if extra_args:
        cmd.extend(extra_args)
    print("[run]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(GPT_ROOT), env=env, check=True)


def _merge_parts(opt_dir: Path, pattern: str, merged_name: str, header: str | None = None) -> Path:
    merged = opt_dir / merged_name
    part = opt_dir / pattern.format(part=0)
    if not part.exists():
        raise FileNotFoundError(part)
    lines: list[str] = []
    if header:
        lines.append(header)
    text = part.read_text(encoding="utf-8").strip()
    if text:
        lines.extend(text.splitlines())
    merged.write_text("\n".join(lines) + "\n", encoding="utf-8")
    part.unlink(missing_ok=True)
    return merged


def prepare_dataset(item: dict[str, Any], exp_name: str, is_half: bool) -> Path:
    opt_dir = GPT_ROOT / "logs" / exp_name
    opt_dir.mkdir(parents=True, exist_ok=True)
    base_env = {
        "inp_text": _as_posix(item["labels_path"]),
        "inp_wav_dir": _as_posix(item["wav_dir"]),
        "exp_name": exp_name,
        "opt_dir": _as_posix(opt_dir),
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": "0",
        "CUDA_VISIBLE_DEVICES": "0",
        "is_half": str(is_half),
        "version": VERSION,
    }
    name2text = opt_dir / "2-name2text.txt"
    semantic = opt_dir / "6-name2semantic.tsv"
    if not name2text.exists():
        env = dict(base_env)
        env["bert_pretrained_dir"] = _as_posix(BERT_DIR)
        _run_python("GPT_SoVITS/prepare_datasets/1-get-text.py", env)
        _merge_parts(opt_dir, "2-name2text-{part}.txt", "2-name2text.txt")
    if not (opt_dir / "5-wav32k").exists() or not any((opt_dir / "5-wav32k").glob("*.wav")):
        env = dict(base_env)
        env["cnhubert_base_dir"] = _as_posix(CNHUBERT_DIR)
        _run_python("GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py", env)
    if not (opt_dir / "7-sv_cn").exists() or not any((opt_dir / "7-sv_cn").glob("*.pt")):
        env = dict(base_env)
        env["sv_path"] = _as_posix(SV_PATH)
        _run_python("GPT_SoVITS/prepare_datasets/2-get-sv.py", env)
    if not semantic.exists():
        env = dict(base_env)
        env["pretrained_s2G"] = _as_posix(PRETRAINED_S2G)
        env["s2config_path"] = _as_posix(S2_CONFIG)
        _run_python("GPT_SoVITS/prepare_datasets/3-get-semantic.py", env)
        _merge_parts(opt_dir, "6-name2semantic-{part}.tsv", "6-name2semantic.tsv", "item_name\tsemantic_audio")
    return opt_dir


def _resolve_project_path(path_value: str) -> str:
    path = Path(str(path_value))
    if not path.is_absolute():
        path = ROOT / path
    return _as_posix(path)


def train_sovits(item: dict[str, Any], exp_name: str, opt_dir: Path, epochs: int, batch_size: int, is_half: bool) -> None:
    data = json.loads(S2_CONFIG.read_text(encoding="utf-8"))
    data["train"]["fp16_run"] = bool(is_half)
    data["train"]["batch_size"] = int(batch_size)
    data["train"]["epochs"] = int(epochs)
    data["train"]["text_low_lr_rate"] = 0.4
    data["train"]["pretrained_s2G"] = _as_posix(PRETRAINED_S2G)
    data["train"]["pretrained_s2D"] = _as_posix(PRETRAINED_S2D)
    data["train"]["if_save_latest"] = True
    data["train"]["if_save_every_weights"] = True
    data["train"]["save_every_epoch"] = int(epochs)
    data["train"]["gpu_numbers"] = "0"
    data["train"]["grad_ckpt"] = True
    data["train"]["lora_rank"] = 16
    data["model"]["version"] = VERSION
    data["data"]["exp_dir"] = _as_posix(opt_dir)
    data["s2_ckpt_dir"] = _as_posix(opt_dir / f"logs_s2_{VERSION}")
    data["save_weight_dir"] = _as_posix(GPT_ROOT / "SoVITS_weights_v2Pro")
    data["name"] = exp_name
    data["version"] = VERSION
    config_path = GPT_ROOT / "TEMP" / f"{exp_name}_s2.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _run_python(
        "GPT_SoVITS/s2_train.py",
        {"_CUDA_VISIBLE_DEVICES": "0", "CUDA_VISIBLE_DEVICES": "0", "is_half": str(is_half)},
        ["--config", _as_posix(config_path)],
    )


def train_gpt(item: dict[str, Any], exp_name: str, opt_dir: Path, epochs: int, batch_size: int, is_half: bool) -> None:
    data = yaml.safe_load(S1_CONFIG.read_text(encoding="utf-8"))
    data["train"]["precision"] = "16-mixed" if is_half else "32"
    data["train"]["batch_size"] = int(batch_size)
    data["train"]["epochs"] = int(epochs)
    data["pretrained_s1"] = _resolve_project_path(item["gpt_model_path"])
    data["train"]["save_every_n_epoch"] = int(epochs)
    data["train"]["if_save_every_weights"] = True
    data["train"]["if_save_latest"] = True
    data["train"]["if_dpo"] = False
    data["train"]["half_weights_save_dir"] = _as_posix(GPT_ROOT / "GPT_weights_v2Pro")
    data["train"]["exp_name"] = exp_name
    data["train_semantic_path"] = _as_posix(opt_dir / "6-name2semantic.tsv")
    data["train_phoneme_path"] = _as_posix(opt_dir / "2-name2text.txt")
    data["output_dir"] = _as_posix(opt_dir / f"logs_s1_{VERSION}")
    config_path = GPT_ROOT / "TEMP" / f"{exp_name}_s1.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _run_python(
        "GPT_SoVITS/s1_train.py",
        {
            "_CUDA_VISIBLE_DEVICES": "0",
            "CUDA_VISIBLE_DEVICES": "0",
            "is_half": str(is_half),
            "hz": "25hz",
        },
        ["--config_file", _as_posix(config_path)],
    )


def _latest_weight(directory: Path, exp_name: str, suffix: str) -> Path:
    matches = [p for p in directory.glob(f"{exp_name}*{suffix}") if p.is_file()]
    if not matches:
        raise FileNotFoundError(f"No {suffix} weight found for {exp_name} in {directory}")
    return max(matches, key=lambda p: p.stat().st_mtime)


def install_weights(item: dict[str, Any], exp_name: str, stamp: str) -> tuple[str, str]:
    slug = item["slug"]
    model_dir = ROOT / "data" / "models" / slug
    model_dir.mkdir(parents=True, exist_ok=True)
    latest_sovits = _latest_weight(GPT_ROOT / "SoVITS_weights_v2Pro", exp_name, ".pth")
    latest_gpt = _latest_weight(GPT_ROOT / "GPT_weights_v2Pro", exp_name, ".ckpt")
    dest_sovits = model_dir / f"{slug}_emotion_{stamp}.pth"
    dest_gpt = model_dir / f"{slug}_emotion_{stamp}.ckpt"
    shutil.copy2(latest_sovits, dest_sovits)
    shutil.copy2(latest_gpt, dest_gpt)
    return dest_gpt.relative_to(ROOT).as_posix(), dest_sovits.relative_to(ROOT).as_posix()


def update_character_weights(name: str, gpt_path: str, sovits_path: str) -> None:
    chars = _load_yaml(CHARS_PATH, [])
    for char in chars:
        if char.get("name") == name:
            char["gpt_model_path"] = gpt_path
            char["sovits_model_path"] = sovits_path
            break
    _write_yaml(CHARS_PATH, chars)


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch fine-tune GPT-SoVITS for Shinsekai characters.")
    parser.add_argument("--sovits-epochs", type=int, default=4)
    parser.add_argument("--gpt-epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--only", default="", help="Comma-separated slugs to train.")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    if not RUNTIME_PY.exists():
        raise FileNotFoundError(RUNTIME_PY)
    manifest = _load_yaml(MANIFEST_PATH, [])
    only = {part.strip() for part in args.only.split(",") if part.strip()}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    is_half = not args.cpu
    trained: list[dict[str, str]] = []

    for item in manifest:
        if only and item["slug"] not in only:
            continue
        if int(item.get("samples") or 0) < 3:
            print(f"[skip] {item['slug']}: not enough samples")
            continue
        exp_name = f"shinsekai_{item['slug']}_emotion"
        print(f"\n=== {item['name']} ({item['slug']}) samples={item['samples']} ===")
        opt_dir = prepare_dataset(item, exp_name, is_half=is_half)
        if args.prepare_only:
            continue
        train_sovits(item, exp_name, opt_dir, args.sovits_epochs, args.batch_size, is_half=is_half)
        train_gpt(item, exp_name, opt_dir, args.gpt_epochs, args.batch_size, is_half=is_half)
        gpt_path, sovits_path = install_weights(item, exp_name, stamp)
        update_character_weights(item["name"], gpt_path, sovits_path)
        trained.append({"name": item["name"], "gpt": gpt_path, "sovits": sovits_path})
        print(f"[installed] {item['name']} -> {gpt_path}, {sovits_path}")

    result_path = ROOT / "data" / "tts_training" / f"last_train_result_{stamp}.yaml"
    _write_yaml(result_path, trained)
    print(f"\nResult: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

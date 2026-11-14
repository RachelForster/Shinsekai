"""Optional GPT-SoVITS v2ProPlus feature extraction (1A/1B/1C) and S2/S1 fine-tuning stages."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

import yaml

from application.characters.voice.pipeline.gsv_runtime import (
    MODEL_VERSION,
    CancellableGsvRunner,
)
from application.runtime.tasks import _update_task


SOVITS_EPOCHS = 8
SOVITS_SAVE_EVERY = 4
GPT_EPOCHS = 15
GPT_SAVE_EVERY = 5

_GPT_WEIGHT_RE = re.compile(r"^(.+)-e(\d+)\.ckpt$", re.IGNORECASE)
_SOVITS_WEIGHT_RE = re.compile(r"^(.+)_e(\d+)_s(\d+)\.pth$", re.IGNORECASE)


def select_latest_trained_weights(gsv_root: Path, exp_name: str) -> tuple[Path, Path]:
    """Locate the highest-epoch/step GPT (.ckpt) and SoVITS (.pth) weights produced for `exp_name`."""
    gpt_dir = gsv_root / "GPT_weights_v2ProPlus"
    sovits_dir = gsv_root / "SoVITS_weights_v2ProPlus"

    gpt_matches: list[tuple[int, float, Path]] = []
    if gpt_dir.is_dir():
        for path in gpt_dir.iterdir():
            if not path.is_file():
                continue
            match = _GPT_WEIGHT_RE.fullmatch(path.name)
            if match and match.group(1) == exp_name:
                gpt_matches.append((int(match.group(2)), path.stat().st_mtime, path))

    sovits_matches: list[tuple[int, int, float, Path]] = []
    if sovits_dir.is_dir():
        for path in sovits_dir.iterdir():
            if not path.is_file():
                continue
            match = _SOVITS_WEIGHT_RE.fullmatch(path.name)
            if match and match.group(1) == exp_name:
                sovits_matches.append(
                    (int(match.group(2)), int(match.group(3)), path.stat().st_mtime, path)
                )

    if not gpt_matches:
        raise RuntimeError(f"未找到训练生成的 GPT 权重（GPT_weights_v2ProPlus/{exp_name}-e*.ckpt）。")
    if not sovits_matches:
        raise RuntimeError(f"未找到训练生成的 SoVITS 权重（SoVITS_weights_v2ProPlus/{exp_name}_e*_s*.pth）。")

    gpt_matches.sort(key=lambda item: (item[0], item[1], item[2].name))
    sovits_matches.sort(key=lambda item: (item[0], item[1], item[2], item[3].name))
    return gpt_matches[-1][2], sovits_matches[-1][3]


def run_v2proplus_training(
    runner: CancellableGsvRunner,
    *,
    exp_name: str,
    sliced_dir: Path,
    list_path: Path,
) -> tuple[Path, Path]:
    """Execute 1A/1B/1C dataset preparation followed by SoVITS and GPT fine-tuning."""
    gsv_root = runner.gsv_root
    profile = runner.profile
    exp_dir = gsv_root / "logs" / exp_name
    if exp_dir.exists():
        shutil.rmtree(exp_dir, ignore_errors=True)
    exp_dir.mkdir(parents=True, exist_ok=True)

    common = {
        "inp_text": str(list_path),
        "inp_wav_dir": str(sliced_dir),
        "exp_name": exp_name,
        "opt_dir": str(exp_dir),
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": profile.gpu,
        "is_half": str(profile.use_half),
        "version": MODEL_VERSION,
    }

    _update_task(
        runner.state,
        runner.task_id,
        phase="train-prepare",
        progress=0.62,
        message="正在提取训练文本、HuBERT 与音色语义特征（1A/1B/1C）。",
    )
    text_env = {
        **common,
        "bert_pretrained_dir": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
    }
    runner.run(
        "1A 文本特征提取",
        runner.python_cmd("GPT_SoVITS/prepare_datasets/1-get-text.py"),
        extra_env=text_env,
    )
    part_txt = exp_dir / "2-name2text-0.txt"
    out_txt = exp_dir / "2-name2text.txt"
    if part_txt.is_file():
        content = part_txt.read_text(encoding="utf-8").strip()
        out_txt.write_text(content + ("\n" if content else ""), encoding="utf-8")
        part_txt.unlink()
    if not out_txt.is_file() or not out_txt.read_text(encoding="utf-8").strip():
        raise RuntimeError("1A 文本特征提取未产出有效结果。")

    hubert_env = {
        **common,
        "cnhubert_base_dir": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
        "sv_path": "GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt",
    }
    runner.run(
        "1B HuBERT/WAV32K 特征提取",
        runner.python_cmd("GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"),
        extra_env=hubert_env,
    )
    runner.run(
        "1B 说话人向量提取",
        runner.python_cmd("GPT_SoVITS/prepare_datasets/2-get-sv.py"),
        extra_env=hubert_env,
    )

    sem_env = {
        **common,
        "pretrained_s2G": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
        "s2config_path": "GPT_SoVITS/configs/s2v2ProPlus.json",
    }
    runner.run(
        "1C 语义 Token 提取",
        runner.python_cmd("GPT_SoVITS/prepare_datasets/3-get-semantic.py"),
        extra_env=sem_env,
    )
    part_sem = exp_dir / "6-name2semantic-0.tsv"
    out_sem = exp_dir / "6-name2semantic.tsv"
    if part_sem.is_file():
        body = part_sem.read_text(encoding="utf-8").strip()
        out_sem.write_text("item_name\tsemantic_audio\n" + body + ("\n" if body else ""), encoding="utf-8")
        part_sem.unlink()
    if not out_sem.is_file() or len(out_sem.read_text(encoding="utf-8").splitlines()) < 2:
        raise RuntimeError("1C 语义特征提取未产出有效结果。")

    _update_task(
        runner.state,
        runner.task_id,
        phase="train-sovits",
        progress=0.74,
        message=f"正在微调 SoVITS 声学模型（{SOVITS_EPOCHS} 轮）。",
    )
    s2_cfg = json.loads((gsv_root / "GPT_SoVITS" / "configs" / "s2v2ProPlus.json").read_text(encoding="utf-8"))
    s2_cfg["train"].update(
        {
            "batch_size": profile.batch_size,
            "epochs": SOVITS_EPOCHS,
            "text_low_lr_rate": 0.4,
            "pretrained_s2G": "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
            "pretrained_s2D": "GPT_SoVITS/pretrained_models/v2Pro/s2Dv2ProPlus.pth",
            "if_save_latest": True,
            "if_save_every_weights": True,
            "save_every_epoch": SOVITS_SAVE_EVERY,
            "gpu_numbers": profile.gpu,
            "grad_ckpt": False,
            "lora_rank": "32",
            "fp16_run": profile.use_half,
        }
    )
    s2_cfg["model"]["version"] = MODEL_VERSION
    s2_cfg["data"]["exp_dir"] = str(exp_dir)
    s2_cfg["s2_ckpt_dir"] = str(exp_dir)
    s2_cfg["save_weight_dir"] = "SoVITS_weights_v2ProPlus"
    s2_cfg["name"] = exp_name
    s2_cfg["version"] = MODEL_VERSION

    (exp_dir / f"logs_s2_{MODEL_VERSION}").mkdir(parents=True, exist_ok=True)
    (gsv_root / "SoVITS_weights_v2ProPlus").mkdir(parents=True, exist_ok=True)
    temp_cfg_dir = gsv_root / "TEMP" / "shinsekai_voice_prepare" / exp_name
    temp_cfg_dir.mkdir(parents=True, exist_ok=True)
    s2_cfg_path = temp_cfg_dir / "s2.json"
    s2_cfg_path.write_text(json.dumps(s2_cfg, ensure_ascii=True, indent=2), encoding="utf-8")

    runner.run(
        "SoVITS 训练",
        runner.python_cmd("GPT_SoVITS/s2_train.py", "--config", str(s2_cfg_path)),
    )

    _update_task(
        runner.state,
        runner.task_id,
        phase="train-gpt",
        progress=0.86,
        message=f"正在微调 GPT 韵律模型（{GPT_EPOCHS} 轮）。",
    )
    s1_cfg = yaml.safe_load((gsv_root / "GPT_SoVITS" / "configs" / "s1longer-v2.yaml").read_text(encoding="utf-8"))
    s1_cfg["train"].update(
        {
            "batch_size": profile.batch_size,
            "epochs": GPT_EPOCHS,
            "save_every_n_epoch": GPT_SAVE_EVERY,
            "if_save_every_weights": True,
            "if_save_latest": True,
            "if_dpo": False,
            "half_weights_save_dir": "GPT_weights_v2ProPlus",
            "exp_name": exp_name,
        }
    )
    if not profile.use_half:
        s1_cfg["train"]["precision"] = "32"
    s1_cfg["pretrained_s1"] = "GPT_SoVITS/pretrained_models/s1v3.ckpt"
    s1_cfg["train_semantic_path"] = str(out_sem)
    s1_cfg["train_phoneme_path"] = str(out_txt)
    s1_cfg["output_dir"] = str(exp_dir / f"logs_s1_{MODEL_VERSION}")

    (gsv_root / "GPT_weights_v2ProPlus").mkdir(parents=True, exist_ok=True)
    s1_cfg_path = temp_cfg_dir / "s1.yaml"
    s1_cfg_path.write_text(yaml.safe_dump(s1_cfg, allow_unicode=False, sort_keys=False), encoding="utf-8")

    runner.run(
        "GPT 训练",
        runner.python_cmd("GPT_SoVITS/s1_train.py", "--config_file", str(s1_cfg_path)),
        extra_env={"_CUDA_VISIBLE_DEVICES": profile.gpu, "hz": "25hz"},
    )

    return select_latest_trained_weights(gsv_root, exp_name)

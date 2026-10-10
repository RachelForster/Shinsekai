"""Model metadata shared by Qwen inference and the existing download service."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from core.model_assets.service import ModelAssetSpec


def complete_qwen_snapshot(directory: Path) -> bool:
    """Check every indexed shard, including partially downloaded snapshots."""
    try:
        for component, filename in (
            ("text_encoder", "model.safetensors.index.json"),
            ("transformer", "diffusion_pytorch_model.safetensors.index.json"),
        ):
            index = json.loads(
                (directory / component / filename).read_text(encoding="utf-8")
            )
            weights = index["weight_map"]
            if not isinstance(weights, dict) or not weights:
                return False
            for name in set(weights.values()):
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                    return False
                shard = directory / component / name
                if not shard.is_file() or shard.stat().st_size == 0:
                    return False
        return all(
            (directory / name).is_file() and (directory / name).stat().st_size > 0
            for name in (
                "model_index.json",
                "processor/tokenizer.json",
                "processor/preprocessor_config.json",
                "text_encoder/config.json",
                "transformer/config.json",
                "scheduler/scheduler_config.json",
                "vae/config.json",
                "vae/diffusion_pytorch_model.safetensors",
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


QWEN_IMAGE21_MODEL_ASSET = ModelAssetSpec(
    asset_id="t2i.qwen-image-2.1",
    title="Qwen-Image-2.1",
    variant="Qwen/Qwen-Image-2.1",
    repo_id="Qwen/Qwen-Image-2.1",
    allow_patterns=(
        "model_index.json",
        "processor/*",
        "scheduler/*",
        "text_encoder/*",
        "transformer/*",
        "vae/*",
        "LICENSE*",
    ),
    required_file_groups=(("model_index.json",),),
    snapshot_validator=complete_qwen_snapshot,
)

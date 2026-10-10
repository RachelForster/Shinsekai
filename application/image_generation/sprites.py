"""Sprite generation through the configured T2I adapter or legacy Gemini."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ai.t2i.t2i_manager import T2IAdapterFactory
from config.config_manager import ConfigManager


def _sprite_edit_prompt(
    prompt: str, reference_count: int, *, qwen: bool = False
) -> str:
    """Anchor sprite edits to the input rather than redescribing its appearance."""
    if reference_count == 1:
        anchor = "the reference image"
        roles = ""
    else:
        anchor = "<image1>" if qwen else "reference image 1"
        roles = f" {anchor} is the canvas and the main source of character identity."
        for index in range(2, reference_count + 1):
            image = f"<image{index}>" if qwen else f"reference image {index}"
            roles += (
                f" {image} is supplementary material; use its details only for the"
                " requested edit, keeping the main character's identity."
            )
    return (
        f"Requested edit: {prompt.strip()}\n"
        f"Edit the existing character in {anchor}.{roles}"
        " Apply only the requested changes. Preserve the character's facial identity,"
        " hairstyle, outfit, accessories, body proportions and illustration style"
        f" from {anchor}, except attributes explicitly requested to change."
        " Preserve the original viewpoint and framing unless the edit requires a change."
        " Produce one sprite of this same character."
    )


def generate_sprites(
    config: ConfigManager,
    *,
    reference_images: Sequence[Path],
    prompts: Sequence[str],
    output_dir: Path,
    provider: str = "gemini",
    seed: int | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[str]:
    if seed is not None and (
        isinstance(seed, bool) or not isinstance(seed, int) or not -1 <= seed < 2**32
    ):
        raise ValueError("seed must be -1 or an unsigned 32-bit integer")
    generation_seed = secrets.randbits(32) if seed == -1 else seed
    if provider == "gemini":
        from tools.generate_sprites import ImageGenerator

        return [
            str(path)
            for path in ImageGenerator().batch_generate_sprites(
                list(reference_images),
                [
                    _sprite_edit_prompt(prompt, len(reference_images))
                    for prompt in prompts
                ],
                output_dir,
            )
        ]
    if provider != "configured":
        raise ValueError("provider must be configured or gemini")
    api = config.config.api_config
    adapter_name = str(api.t2i_provider or "comfyui").strip()
    if adapter_name.lower() == "comfyui" and not api.t2i_default_workflow_path:
        raise ValueError("Configure an image generation provider in AI services first")
    adapter = T2IAdapterFactory.create_adapter(
        adapter_name,
        **config.merged_t2i_factory_kwargs(
            adapter_name,
            {
                "work_path": api.t2i_work_path,
                "api_url": api.t2i_api_url,
                "workflow_path": api.t2i_default_workflow_path,
                "prompt_node_id": api.t2i_prompt_node_id,
                "output_node_id": api.t2i_output_node_id,
            },
        ),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    batch_id = uuid.uuid4().hex[:12]
    try:
        for index, prompt in enumerate(prompts):

            def progress(value: float, message: str) -> None:
                if on_progress:
                    on_progress(
                        (index + max(0, min(1, value))) / len(prompts),
                        f"{index + 1}/{len(prompts)} · {message}",
                    )

            progress(0, "Generating sprite")
            options: dict[str, Any] = {}
            if generation_seed is not None:
                options["seed"] = generation_seed
            if adapter_name.lower() == "qwen-image-2.1":
                options.update(
                    transparent=True, reference_canvas_index=0, on_progress=progress
                )
            result = adapter.generate_image(
                _sprite_edit_prompt(
                    prompt,
                    len(reference_images),
                    qwen=adapter_name.lower() == "qwen-image-2.1",
                ),
                str(output_dir / f"sprite_{batch_id}_{index + 1:03d}.png"),
                reference_images=reference_images,
                **options,
            )
            if not result or not Path(result).is_file():
                raise RuntimeError(
                    f"Image generation returned no sprite for prompt {index + 1}"
                )
            files.append(str(result))
            progress(1, "Sprite saved")
        return files
    finally:
        adapter.shutdown()

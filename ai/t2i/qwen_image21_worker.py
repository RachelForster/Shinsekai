"""Standalone worker source, packaged as code rather than an external resource.

Executed only by the configured Python interpreter. Heavy dependencies never
enter the app process and cannot replace its Transformers 4 runtime.
"""

WORKER_SOURCE = r"""
import contextlib
import gc
import json
import os
import sys
from pathlib import Path

protocol_stdout = sys.stdout


def emit(kind, **fields):
    protocol_stdout.write(json.dumps({"type": kind, **fields}, ensure_ascii=False) + "\n")
    protocol_stdout.flush()


def generate(request):
    dependency_path = request.get("dependency_path")
    if dependency_path:
        if not Path(dependency_path).is_dir():
            raise ValueError("Configured dependency_path is not a directory")
        sys.path.insert(0, dependency_path)
    try:
        import torch
        from PIL import Image
        from diffusers import (
            AutoencoderKLQwenImage21, BitsAndBytesConfig as DiffusersBitsAndBytesConfig,
            FlowMatchEulerDiscreteScheduler, QwenImage21Pipeline, QwenImage21Transformer2DModel,
        )
        from diffusers.pipelines.qwenimage21.pipeline_qwenimage21 import calculate_dimensions
        from transformers import (
            BitsAndBytesConfig as TransformersBitsAndBytesConfig,
            Qwen3VLForConditionalGeneration, Qwen3VLProcessor,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Qwen worker dependencies are unavailable. Configure an isolated Python environment "
            "with ai/t2i/requirements-qwen-image21.txt (Transformers 5 is required). " + str(exc)
        ) from exc
    if not torch.cuda.is_available():
        raise RuntimeError("Local Qwen-Image-2.1 requires a CUDA GPU and CUDA-enabled PyTorch")
    torch.set_grad_enabled(False)
    torch.set_num_threads(4)
    model = Path(request["model_path"])
    prompt = request["prompt"]
    if request.get("transparent"):
        prompt += " This is an RGBA image with transparency. The image has an alpha channel and the background is completely transparent."
    images = []
    for path in request["reference_images"]:
        with Image.open(path) as source:
            images.append(source.convert("RGBA"))
    resolution = request["resolution"]
    dimensions = {key: request[key] for key in ("width", "height") if key in request}
    if request.get("reference_canvas_index") is not None:
        canvas = images[request["reference_canvas_index"]]
        width, height, _ = calculate_dimensions(resolution ** 2, canvas.width / canvas.height)
        dimensions.setdefault("width", width)
        dimensions.setdefault("height", height)
    emit("progress", progress=0.05, message="Loading Qwen vision/text encoder")
    processor = Qwen3VLProcessor.from_pretrained(model / "processor", local_files_only=True)
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(model / "scheduler", local_files_only=True)
    encoder = Qwen3VLForConditionalGeneration.from_pretrained(
        model / "text_encoder", local_files_only=True, dtype=torch.bfloat16,
        quantization_config=TransformersBitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        ), device_map={"": 0}, low_cpu_mem_usage=True,
    ).eval()
    encoder_pipe = QwenImage21Pipeline(scheduler=scheduler, vae=None, text_encoder=encoder, processor=processor, transformer=None)
    references = []
    for image in images:
        width, height, _ = calculate_dimensions(resolution ** 2, image.width / image.height)
        references.append(encoder_pipe.image_processor.resize(image, width=width, height=height))
    emit("progress", progress=0.15, message="Encoding prompt and reference images")
    encoded = encoder_pipe.encode_prompt(prompt=prompt, image=references or None, device=torch.device("cuda"))
    encoded = tuple(tensor.cpu() if tensor is not None else None for tensor in encoded)
    del encoder_pipe, encoder, references
    gc.collect()
    torch.cuda.empty_cache()

    class CachedPromptPipeline(QwenImage21Pipeline):
        def encode_prompt(self, *args, **kwargs):
            # Keep image_pad_mask: __call__ does not accept this third output
            # with precomputed embeddings in Diffusers 0.41.
            device = kwargs.get("device", torch.device("cuda"))
            return tuple(tensor.to(device) if tensor is not None else None for tensor in encoded)

    emit("progress", progress=0.25, message="Loading quantized Qwen diffusion transformer")
    quantization = DiffusersBitsAndBytesConfig(load_in_8bit=True) if request["transformer_bits"] == 8 else DiffusersBitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
    )
    transformer = QwenImage21Transformer2DModel.from_pretrained(
        model / "transformer", local_files_only=True, torch_dtype=torch.bfloat16,
        quantization_config=quantization, low_cpu_mem_usage=True,
    ).eval()
    vae = AutoencoderKLQwenImage21.from_pretrained(model / "vae", local_files_only=True, torch_dtype=torch.bfloat16).to("cuda").eval()
    pipe = CachedPromptPipeline(scheduler=scheduler, vae=vae, text_encoder=None, processor=processor, transformer=transformer)
    pipe.set_progress_bar_config(disable=True)
    pipe.to("cuda")
    steps = request["steps"]

    def step_callback(pipeline, step, timestep, values):
        emit("progress", progress=0.35 + 0.55 * (step + 1) / steps, message=f"Generating image: {step + 1}/{steps}")
        if step + 1 == steps:
            torch.cuda.synchronize()
            pipeline.transformer.to("cpu")
            torch.cuda.empty_cache()
            emit("progress", progress=0.92, message="Decoding RGBA image")
        return values

    seed = request["seed"]
    if seed < 0:
        seed = int.from_bytes(os.urandom(4), "big")
    result = pipe(
        prompt=prompt, image=images or None, **dimensions, output_resolution=resolution,
        num_inference_steps=steps, true_cfg_scale=1.0, use_kv_cache=True,
        generator=torch.Generator("cuda").manual_seed(seed), callback_on_step_end=step_callback,
    ).images[0]
    if request.get("transparent"):
        import numpy as np
        pixels = np.array(result.convert("RGBA"))
        pixels[pixels[:, :, 3] < 10] = 0
        result = Image.fromarray(pixels)
    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        result.save(temporary, format="PNG")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    emit("result", path=str(output))


try:
    request = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        generate(request)
except Exception as exc:
    emit("error", message=str(exc))
    sys.exit(1)
"""

"""Stable Diffusion HTTP text-to-image adapter."""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

import requests

from core.adapters import builtin_adapter
from sdk.adapters.t2i import T2IAdapter


@builtin_adapter("stable diffusion", label="Stable Diffusion", order=20)
class StableDiffusionAdapter(T2IAdapter):
    """Adapter for a Stable Diffusion (e.g., AUTOMATIC1111/ComfyUI) API."""

    supports_reference_images = True

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:7860/sdapi/v1/txt2img",
        default_model: Optional[str] = None,
    ) -> None:
        self.api_url = api_url
        self.current_model = default_model
        print(f"StableDiffusionAdapter initialized with API: {self.api_url}")

    def generate_image(
        self,
        prompt: str,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """Generate a T2I image using the Stable Diffusion HTTP API."""
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": kwargs.get("negative_prompt", "ugly, deformed, low quality"),
            "steps": kwargs.get("steps", 20),
            "width": kwargs.get("width", 1024),
            "height": kwargs.get("height", 1024),
            "sampler_name": kwargs.get("sampler_name", "Euler a"),
            "cfg_scale": kwargs.get("cfg_scale", 7),
            "seed": kwargs.get("seed", -1),
        }

        if self.current_model:
            pass

        endpoint = self.api_url
        reference = kwargs.get("reference_image_path")
        if reference:
            with open(reference, "rb") as source:
                payload["init_images"] = [base64.b64encode(source.read()).decode("ascii")]
            payload["denoising_strength"] = kwargs.get("denoising_strength", 0.65)
            if "/txt2img" not in endpoint and "/img2img" not in endpoint:
                raise ValueError(
                    "参考图需要配置 Stable Diffusion 的 /sdapi/v1/txt2img 或 /img2img 地址"
                )
            endpoint = endpoint.replace("/txt2img", "/img2img")
        try:
            response = requests.post(endpoint, json=payload, timeout=600)
            response.raise_for_status()

            data = response.json()
            if not data.get("images"):
                print("Stable Diffusion API returned no images.")
                return None

            image_data = base64.b64decode(data["images"][0])

            if not file_path:
                file_path = os.path.join(os.getcwd(), "temp_t2i_sd.png")

            with open(file_path, "wb") as f:
                f.write(image_data)

            return os.path.abspath(file_path)
        except Exception as e:
            print(f"Stable Diffusion T2I generation failed: {e}")
            return None

    def switch_model(self, model_info: Dict[str, Any]) -> None:
        """Switch the active Stable Diffusion checkpoint model."""
        model_checkpoint = model_info.get("model_checkpoint", "")

        if model_checkpoint and self.current_model != model_checkpoint:
            print(f"Switching Stable Diffusion model to: {model_checkpoint}")
            self.current_model = model_checkpoint

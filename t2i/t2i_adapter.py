import os
import subprocess
import base64
import copy
import json
import time
import requests
import secrets
from typing import Optional, Dict, Any

from sdk.adapters.t2i import T2IAdapter


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_size(size: Any, fallback: str = "1024x1024") -> tuple[int, int]:
    text = str(size or fallback).strip().lower().replace(" ", "")
    if text == "auto":
        text = fallback
    try:
        width_text, height_text = text.split("x", 1)
        return max(64, int(width_text)), max(64, int(height_text))
    except Exception:
        width_text, height_text = fallback.lower().split("x", 1)
        return int(width_text), int(height_text)


def _infer_image_size(
    prompt: str,
    square_size: str,
    portrait_size: str,
    landscape_size: str,
    explicit_size: Optional[Any] = None,
) -> str:
    if explicit_size:
        named_size = str(explicit_size).strip().lower()
        if named_size in {"landscape", "wide", "horizontal", "cg"}:
            return landscape_size
        if named_size in {"portrait", "vertical", "character", "sprite"}:
            return portrait_size
        if named_size in {"square", "default"}:
            return square_size
        return str(explicit_size)

    text = str(prompt or "").lower()
    no_person_markers = (
        "no person",
        "no people",
        "empty scene",
        "pure scenery",
        "pure senery",
        "background only",
        "无人物",
        "无人",
        "纯背景",
        "纯风景",
        "背景图",
    )
    person_markers = (
        "1girl",
        "1boy",
        "girl",
        "boy",
        "woman",
        "man",
        "character",
        "portrait",
        "full body",
        "upper body",
        "looking at viewer",
        "角色",
        "人物",
        "立绘",
        "全身",
        "半身",
        "头像",
    )
    landscape_markers = (
        "landscape",
        "scenery",
        "senery",
        "wide shot",
        "panoramic",
        "room",
        "street",
        "classroom",
        "library",
        "restaurant",
        "corridor",
        "beach",
        "city",
        "forest",
        "背景",
        "风景",
        "场景",
        "街道",
        "房间",
        "卧室",
        "教室",
        "图书馆",
        "餐厅",
        "走廊",
        "城市",
        "森林",
        "海边",
    )

    has_no_person = any(marker in text for marker in no_person_markers)
    has_person = any(marker in text for marker in person_markers)
    has_landscape = any(marker in text for marker in landscape_markers)

    if has_person and not has_no_person:
        return portrait_size
    if has_landscape or has_no_person:
        return landscape_size
    return square_size


class StableDiffusionAdapter(T2IAdapter):
    """
    Adapter for a Stable Diffusion (e.g., AUTOMATIC1111/ComfyUI) API.
    It adapts the T2I API to the standard T2IAdapter interface.
    """
    def __init__(self, api_url: str = "http://127.0.0.1:7860/sdapi/v1/txt2img", default_model: Optional[str] = None):
        self.api_url = api_url
        self.current_model = default_model
        print(f"StableDiffusionAdapter initialized with API: {self.api_url}")

    def generate_image(self, prompt: str, file_path: Optional[str] = None, **kwargs) -> Optional[str]:
        """
        Generates a T2I image using the Stable Diffusion API.
        The kwargs dictionary can include parameters like negative_prompt, steps, etc.
        """
        # A simplified payload for a standard SD API
        payload = {
            "prompt": prompt,
            "negative_prompt": kwargs.get("negative_prompt", "ugly, deformed, low quality"),
            "steps": kwargs.get("steps", 20),
            "width": kwargs.get("width", 1024),
            "height": kwargs.get("height", 1024),
            "sampler_name": kwargs.get("sampler_name", "Euler a"),
            "cfg_scale": kwargs.get("cfg_scale", 7),
            "seed": kwargs.get("seed", -1),
        }
        
        # Add the checkpoint model if set
        if self.current_model:
            # Assuming a specific endpoint or method to switch model isn't used here,
            # but rather the payload includes the override. This varies by API.
            pass

        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status() # Raise an exception for bad status codes
            
            # The response content is often a JSON object with base64 encoded images
            data = response.json()
            if not data.get("images"):
                print("Stable Diffusion API returned no images.")
                return None
            
            # Decode the base64 image and save it
            import base64
            image_data = base64.b64decode(data['images'][0])
            
            if not file_path:
                # Placeholder for dynamic file naming
                file_path = os.path.join(os.getcwd(), "temp_t2i_sd.png")

            with open(file_path, 'wb') as f:
                f.write(image_data)

            return os.path.abspath(file_path)
        except Exception as e:
            print(f"Stable Diffusion T2I generation failed: {e}")
            return None

    def switch_model(self, model_info: Dict[str, Any]):
        """
        Switches the Stable Diffusion model (checkpoint).
        `model_info` is expected to be a dictionary with 'model_checkpoint' key.
        """
        model_checkpoint = model_info.get('model_checkpoint', '')
        
        if model_checkpoint and self.current_model != model_checkpoint:
            print(f"Switching Stable Diffusion model to: {model_checkpoint}")
            self.current_model = model_checkpoint
            # In a real-world scenario, you might call a separate API endpoint to load the model
            # e.g., requests.post("http://127.0.0.1:7860/sdapi/v1/options", json={"sd_model_checkpoint": model_checkpoint})


class OpenAIImageAdapter(T2IAdapter):
    """OpenAI/NewAPI compatible image generation adapter."""

    def __init__(
        self,
        api_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-image-2",
        size: str = "1024x1024",
        auto_size: bool = True,
        square_size: str = "1024x1024",
        portrait_size: str = "1024x1536",
        landscape_size: str = "1536x1024",
        quality: str = "low",
        response_format: str = "b64_json",
        moderation: str = "",
        fallback_models: Optional[Any] = None,
        fallback_configs: Optional[Any] = None,
        timeout_seconds: int = 180,
        **kwargs,
    ):
        self.api_url = str(api_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "gpt-image-2")
        self.size = str(size or "1024x1024")
        self.auto_size = _coerce_bool(auto_size, True)
        self.square_size = str(square_size or "1024x1024")
        self.portrait_size = str(portrait_size or "1024x1536")
        self.landscape_size = str(landscape_size or "1536x1024")
        self.quality = str(quality or "low")
        self.response_format = str(response_format or "").strip()
        self.moderation = str(moderation or "").strip()
        self.fallback_models = self._normalize_fallback_models(fallback_models)
        self.fallback_configs = self._normalize_fallback_configs(fallback_configs)
        self.timeout_seconds = int(timeout_seconds or 180)
        print(f"OpenAIImageAdapter initialized with model: {self.model}")

    def _normalize_fallback_models(self, fallback_models: Optional[Any]) -> list[str]:
        if not fallback_models:
            return []
        if isinstance(fallback_models, str):
            models = fallback_models.split(",")
        elif isinstance(fallback_models, (list, tuple, set)):
            models = fallback_models
        else:
            models = [fallback_models]
        return [
            str(model).strip()
            for model in models
            if str(model).strip() and str(model).strip() != self.model
        ]

    def _normalize_fallback_configs(self, fallback_configs: Optional[Any]) -> list[dict[str, Any]]:
        if not fallback_configs:
            return []
        configs = fallback_configs
        if isinstance(configs, str):
            try:
                configs = json.loads(configs)
            except Exception:
                return []
        if isinstance(configs, dict):
            configs = [configs]
        if not isinstance(configs, list):
            return []
        return [dict(item) for item in configs if isinstance(item, dict) and item.get("model")]

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_key": {
                "type": "password",
                "label": "Image API Key",
                "default": "",
            },
            "model": {
                "type": "str",
                "label": "Image model",
                "default": "gpt-image-2",
            },
            "size": {
                "type": "str",
                "label": "Image size",
                "default": "1024x1024",
                "choices": ["1024x1024", "1024x1536", "1536x1024", "auto"],
            },
            "auto_size": {
                "type": "bool",
                "label": "Auto choose size by prompt",
                "default": True,
            },
            "square_size": {
                "type": "str",
                "label": "Square image size",
                "default": "1024x1024",
            },
            "portrait_size": {
                "type": "str",
                "label": "Portrait image size",
                "default": "1024x1536",
            },
            "landscape_size": {
                "type": "str",
                "label": "Landscape image size",
                "default": "1536x1024",
            },
            "quality": {
                "type": "str",
                "label": "Image quality",
                "default": "low",
                "choices": ["low", "medium", "high", "auto"],
            },
            "response_format": {
                "type": "str",
                "label": "Response format",
                "default": "b64_json",
                "choices": ["b64_json", "url", ""],
            },
            "moderation": {
                "type": "str",
                "label": "Image moderation",
                "default": "",
                "choices": ["", "low", "auto"],
            },
            "fallback_models": {
                "type": "str",
                "label": "Fallback image models",
                "default": "",
            },
            "fallback_configs": {
                "type": "list",
                "label": "Fallback image provider configs",
                "default": [],
            },
            "timeout_seconds": {
                "type": "int",
                "label": "Timeout seconds",
                "default": 180,
                "min": 30,
                "max": 600,
            },
        }

    def _generation_endpoint(self, api_url: Optional[str] = None) -> str:
        base = str(api_url or self.api_url).rstrip("/")
        if base.endswith("/images/generations"):
            return base
        if base.endswith("/v1"):
            return base + "/images/generations"
        return base + "/v1/images/generations"

    def _headers(self, api_key: Optional[str] = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key if api_key is not None else self.api_key}",
            "Content-Type": "application/json",
        }

    def _resolve_size(self, prompt: str, explicit_size: Optional[Any] = None) -> str:
        if explicit_size or self.auto_size or self.size == "auto":
            return _infer_image_size(
                prompt,
                square_size=self.square_size,
                portrait_size=self.portrait_size,
                landscape_size=self.landscape_size,
                explicit_size=explicit_size,
            )
        return self.size

    def _payload(
        self,
        prompt: str,
        include_optional: bool = True,
        model: Optional[str] = None,
        explicit_size: Optional[Any] = None,
        quality: Optional[str] = None,
        response_format: Optional[str] = None,
        moderation: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "n": 1,
        }
        response_format = self.response_format if response_format is None else str(response_format or "").strip()
        quality = self.quality if quality is None else str(quality or "").strip()
        moderation = self.moderation if moderation is None else str(moderation or "").strip()
        if response_format:
            payload["response_format"] = response_format
        if include_optional:
            resolved_size = self._resolve_size(prompt, explicit_size)
            if resolved_size:
                payload["size"] = resolved_size
            if quality:
                payload["quality"] = quality
            if moderation:
                payload["moderation"] = moderation
        return payload

    def _generation_configs(self) -> list[dict[str, Any]]:
        primary = {
            "api_url": self.api_url,
            "api_key": self.api_key,
            "model": self.model,
            "quality": self.quality,
            "response_format": self.response_format,
            "moderation": self.moderation,
        }
        configs = [primary]
        configs.extend({**primary, "model": model} for model in self.fallback_models)
        for config in self.fallback_configs:
            merged = {**primary, **config}
            configs.append(merged)
        return configs

    def _save_image_bytes(self, image_data: bytes, file_path: Optional[str]) -> str:
        if not file_path:
            file_path = os.path.join(os.getcwd(), "temp_openai_image.png")
        with open(file_path, "wb") as f:
            f.write(image_data)
        return os.path.abspath(file_path)

    def generate_image(self, prompt: str, file_path: Optional[str] = None, **kwargs) -> Optional[str]:
        if not self.api_key:
            print("OpenAI image generation failed: missing API key.")
            return None

        prompt = str(prompt or "").strip()
        if not prompt:
            print("OpenAI image generation failed: empty prompt.")
            return None

        last_error: Optional[Exception] = None
        explicit_size = kwargs.get("size") or kwargs.get("image_size")
        resolved_size = self._resolve_size(prompt, explicit_size)
        print(f"OpenAI image generation using size: {resolved_size}")
        configs = self._generation_configs()
        for index, config in enumerate(configs):
            model = str(config.get("model") or self.model)
            api_key = str(config.get("api_key") or "")
            api_url = str(config.get("api_url") or self.api_url)
            if not api_key:
                print(f"OpenAI image generation skipped model '{model}': missing API key.")
                continue
            try:
                endpoint = self._generation_endpoint(api_url)
                payload = self._payload(
                    prompt,
                    include_optional=True,
                    model=model,
                    explicit_size=resolved_size,
                    quality=config.get("quality", self.quality),
                    response_format=config.get("response_format", self.response_format),
                    moderation=config.get("moderation", self.moderation),
                )
                response = requests.post(
                    endpoint,
                    headers=self._headers(api_key),
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 400:
                    minimal_payload = self._payload(
                        prompt,
                        include_optional=True,
                        model=model,
                        explicit_size=resolved_size,
                        quality="",
                        response_format=config.get("response_format", self.response_format),
                        moderation="",
                    )
                    response = requests.post(
                        endpoint,
                        headers=self._headers(api_key),
                        json=minimal_payload,
                        timeout=self.timeout_seconds,
                    )
                if response.status_code >= 500 and index < len(configs) - 1:
                    next_model = str(configs[index + 1].get("model") or self.model)
                    print(
                        "OpenAI image generation model "
                        f"'{model}' returned {response.status_code}; trying fallback '{next_model}'."
                    )
                    continue
                response.raise_for_status()
                data = response.json()
                item = (data.get("data") or [{}])[0]
                if item.get("b64_json"):
                    image_data = base64.b64decode(item["b64_json"])
                    return self._save_image_bytes(image_data, file_path)
                if item.get("url"):
                    image_response = requests.get(item["url"], timeout=self.timeout_seconds)
                    image_response.raise_for_status()
                    return self._save_image_bytes(image_response.content, file_path)
                print("OpenAI image generation failed: response contained no image data.")
                return None
            except Exception as e:
                last_error = e
                if index < len(configs) - 1:
                    next_model = str(configs[index + 1].get("model") or self.model)
                    print(
                        "OpenAI image generation model "
                        f"'{model}' failed; trying fallback '{next_model}'."
                    )
                    continue
        print(f"OpenAI image generation failed: {last_error}")
        return None

    def switch_model(self, model_info: Dict[str, Any]):
        model = model_info.get("model") if model_info else None
        if model:
            self.model = str(model)


class ComfyUIT2IAdapter(T2IAdapter):
    """
    Adapter for the ComfyUI Text-to-Image service API.
    It executes a predefined ComfyUI workflow by injecting the prompt.
    """
    
    # ------------------ ComfyUI API Endpoints ------------------
    # NOTE: You must have a ComfyUI instance running with the API enabled.
    PROMPT_ENDPOINT = "/prompt"
    HISTORY_ENDPOINT = "/history"
    
    def __init__(self, 
                 api_url: str = "http://127.0.0.1:8188", 
                 work_path: str = "",
                 workflow_path: str = "path/to/default_workflow.json",
                 prompt_node_id: str = "6", # Common ID for the CLIPTextEncode (Prompt) node in SD workflows
                 output_node_id: str = "17", # Common ID for the SaveImage node
                 auto_size: bool = True,
                 square_size: str = "768x768",
                 portrait_size: str = "576x896",
                 landscape_size: str = "832x512",
                 size_node_id: str = "",
                 width_input_name: str = "width",
                 height_input_name: str = "height",
                 launch_args: Optional[list[str] | str] = None,
                 timeout_seconds: int = 180,
                 prompt_prefix: str = "",
                 negative_prompt: str = "",
                 negative_prompt_node_id: str = ""):# Common ID for EmptyLatentImage size inputs
        """
        初始化 ComfyUI Adapter。

        Args:
            api_url (str): ComfyUI 服务器的 API 地址 (不含 /api)。
            workflow_path (str): 预先导出的 ComfyUI 工作流 JSON 文件路径。
            prompt_node_id (str): 工作流 JSON 中用于接收文本提示的节点的 ID。
            output_node_id (str): 工作流 JSON 中用于保存或返回图像的节点的 ID (通常是 Save Image 节点)。
        """
        self.api_url = api_url.rstrip('/')
        self.workflow_path = workflow_path
        self.prompt_node_id = prompt_node_id
        self.output_node_id = output_node_id
        self.work_path = work_path
        self.auto_size = _coerce_bool(auto_size, True)
        self.square_size = str(square_size or "768x768")
        self.portrait_size = str(portrait_size or "576x896")
        self.landscape_size = str(landscape_size or "832x512")
        self.size_node_id = str(size_node_id or "")
        self.width_input_name = str(width_input_name or "width")
        self.height_input_name = str(height_input_name or "height")
        self.launch_args = self._normalize_launch_args(launch_args)
        self.prompt_prefix = str(prompt_prefix or "").strip()
        self.negative_prompt = str(negative_prompt or "").strip()
        self.negative_prompt_node_id = str(negative_prompt_node_id or "").strip()
        try:
            self.timeout_seconds = max(30, int(timeout_seconds))
        except Exception:
            self.timeout_seconds = 180
        self.workflow_template = self._load_workflow_template()
        self._start_server_process()

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "api_url": {
                "type": "str",
                "label": "ComfyUI API URL",
                "default": "http://127.0.0.1:8188",
            },
            "work_path": {
                "type": "str",
                "label": "ComfyUI portable root",
                "default": "",
            },
            "workflow_path": {
                "type": "str",
                "label": "Workflow JSON path",
                "default": "",
            },
            "prompt_node_id": {
                "type": "str",
                "label": "Prompt node ID",
                "default": "6",
            },
            "output_node_id": {
                "type": "str",
                "label": "Output node ID",
                "default": "17",
            },
            "auto_size": {
                "type": "bool",
                "label": "Auto choose size by prompt",
                "default": True,
            },
            "square_size": {
                "type": "str",
                "label": "Square latent size",
                "default": "768x768",
            },
            "portrait_size": {
                "type": "str",
                "label": "Portrait latent size",
                "default": "576x896",
            },
            "landscape_size": {
                "type": "str",
                "label": "Landscape latent size",
                "default": "832x512",
            },
            "size_node_id": {
                "type": "str",
                "label": "Optional size node ID",
                "default": "",
            },
            "launch_args": {
                "type": "str",
                "label": "ComfyUI launch args",
                "default": "--lowvram",
            },
            "timeout_seconds": {
                "type": "int",
                "label": "Generation timeout seconds",
                "default": 180,
            },
            "prompt_prefix": {
                "type": "str",
                "label": "Prompt prefix",
                "default": "",
            },
            "negative_prompt": {
                "type": "str",
                "label": "Negative prompt",
                "default": "",
            },
            "negative_prompt_node_id": {
                "type": "str",
                "label": "Negative prompt node ID",
                "default": "",
            },
        }

    @staticmethod
    def _normalize_launch_args(raw: Optional[list[str] | str]) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            return [str(x).strip() for x in raw if str(x).strip()]
        text = str(raw).strip()
        if not text:
            return []
        import shlex

        try:
            return shlex.split(text, posix=False)
        except Exception:
            return text.split()

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        try:
            # You might want to add a check here to see if the process is already running
            response = requests.get(self.api_url)
            if response.status_code == 200:
                print("ComfyUI server is already running.")
                return
        except requests.exceptions.ConnectionError:
            print("ComfyUI server not found, attempting to start...")

        if self.work_path=="":
            return

        os_path = os.path.abspath(self.work_path)
        candidates = [
            (
                os.path.join(os_path, "python_embeded", "python.exe"),
                os.path.join(os_path, "ComfyUI", "main.py"),
                os_path,
            ),
            (
                os.path.join(os_path, "venv", "Scripts", "python.exe"),
                os.path.join(os_path, "ComfyUI", "main.py"),
                os.path.join(os_path, "ComfyUI"),
            ),
            (
                os.path.join(os_path, ".venv", "Scripts", "python.exe"),
                os.path.join(os_path, "ComfyUI", "main.py"),
                os.path.join(os_path, "ComfyUI"),
            ),
            (
                os.path.join(os.path.dirname(os_path), "venv", "Scripts", "python.exe"),
                os.path.join(os_path, "main.py"),
                os_path,
            ),
        ]
        for python_path, api_path, cwd in candidates:
            if os.path.exists(python_path) and os.path.exists(api_path):
                subprocess.Popen([python_path, api_path, *self.launch_args], cwd=cwd)
                print("ComfyUI server starting...")
                return
        print(f"ComfyUI server launch skipped: no supported Python/main.py layout under {os_path}")

    def _load_workflow_template(self) -> Dict[str, Any]:
        """加载 ComfyUI 工作流 JSON 文件作为模板。"""
        try:
            with open(self.workflow_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading ComfyUI workflow template from {self.workflow_path}: {e}")
            raise

    def _resolve_size(self, prompt: str, explicit_size: Optional[Any] = None) -> str:
        if explicit_size or self.auto_size:
            return _infer_image_size(
                prompt,
                square_size=self.square_size,
                portrait_size=self.portrait_size,
                landscape_size=self.landscape_size,
                explicit_size=explicit_size,
            )
        return self.square_size

    def _inject_size(self, prompt_workflow: Dict[str, Any], prompt: str, explicit_size: Optional[Any] = None) -> None:
        width, height = _parse_size(self._resolve_size(prompt, explicit_size), fallback=self.square_size)

        candidate_ids: list[str] = []
        if self.size_node_id:
            candidate_ids.append(self.size_node_id)
        candidate_ids.extend(
            node_id
            for node_id, node in prompt_workflow.items()
            if isinstance(node, dict)
            and isinstance(node.get("inputs"), dict)
            and self.width_input_name in node["inputs"]
            and self.height_input_name in node["inputs"]
            and node_id not in candidate_ids
        )

        if not candidate_ids:
            print("ComfyUI workflow has no width/height node; using workflow default size.")
            return

        for node_id in candidate_ids:
            node = prompt_workflow.get(node_id)
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            node["inputs"][self.width_input_name] = width
            node["inputs"][self.height_input_name] = height
        print(f"ComfyUI image generation using size: {width}x{height}")

    def _inject_seed(self, prompt_workflow: Dict[str, Any], seed: Optional[Any] = None) -> None:
        try:
            seed_value = int(seed) if seed is not None else secrets.randbelow(2**48)
        except Exception:
            seed_value = secrets.randbelow(2**48)
        for node in prompt_workflow.values():
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            inputs = node["inputs"]
            for key in ("seed", "noise_seed"):
                if key in inputs:
                    inputs[key] = seed_value

    def generate_image(self, prompt: str, file_path: Optional[str] = None, **kwargs) -> Optional[str]:
        """
        生成图像。通过修改工作流中的 prompt 节点并提交执行。
        
        Args:
            prompt (str): 图像生成的文本提示。
            file_path (str, optional): 图像保存路径。
            **kwargs: 额外的参数，如 'negative_prompt'，或特定节点ID以覆盖参数。

        Returns:
            str: 生成图像的绝对路径，失败返回 None。
        """
        if not self.workflow_template:
            return None

        # 1. 深度复制模板以避免修改原始结构
        prompt_workflow = copy.deepcopy(self.workflow_template)
        
        # 2. 注入主 Prompt
        # 假设 CLIPTextEncode 节点 (ID: self.prompt_node_id) 的输入是 index 1
        if self.prompt_node_id in prompt_workflow:
            final_prompt = prompt
            if self.prompt_prefix:
                final_prompt = f"{self.prompt_prefix}, {prompt}".strip(" ,")
            prompt_workflow[self.prompt_node_id]["inputs"]["text"] = final_prompt
        else:
            print(f"Error: Prompt node ID '{self.prompt_node_id}' not found in workflow.")
            return None
        if self.negative_prompt and self.negative_prompt_node_id in prompt_workflow:
            prompt_workflow[self.negative_prompt_node_id]["inputs"]["text"] = self.negative_prompt

        self._inject_size(
            prompt_workflow,
            prompt=prompt,
            explicit_size=kwargs.get("size") or kwargs.get("image_size"),
        )
        self._inject_seed(prompt_workflow, kwargs.get("seed"))

        payload = {
            "prompt": prompt_workflow,
            "client_id": str(time.time()), # 简单的唯一标识符
            "extra_data": {}
        }

        try:
            response = requests.post(self.api_url + self.PROMPT_ENDPOINT, json=payload)
            response.raise_for_status()
            prompt_data = response.json()
            prompt_id = prompt_data.get("prompt_id")
            
            if not prompt_id:
                print("ComfyUI API failed to return a prompt_id.")
                return None

            print(f"Workflow submitted. Prompt ID: {prompt_id}. Waiting for completion...")
            return self._wait_for_and_get_image(prompt_id, file_path)

        except Exception as e:
            print(f"ComfyUI T2I generation failed: {e}")
            return None

    def _wait_for_and_get_image(self, prompt_id: str, file_path: Optional[str]) -> Optional[str]:
        """轮询历史记录以查找生成的图像文件。"""
        # 简单轮询，默认最多等待 180 秒（本地 6GB 显卡第一次加载模型会更慢）
        for _ in range(max(1, self.timeout_seconds // 2)):
            time.sleep(2)
            try:
                history_response = requests.get(f"{self.api_url}{self.HISTORY_ENDPOINT}/{prompt_id}")
                history_response.raise_for_status()
                history_data = history_response.json()

                if prompt_id in history_data:
                    # 查找 SaveImage 节点的输出
                    output = history_data[prompt_id]["outputs"].get(self.output_node_id)
                    
                    if output and "images" in output and output["images"]:
                        image_info = output["images"][0] # 假设只生成一张图
                        filename = image_info["filename"]
                        subfolder = image_info["subfolder"]
                        
                        # 构造图像下载 URL
                        image_url = (f"{self.api_url}/view?"
                                     f"filename={filename}&"
                                     f"subfolder={subfolder}&"
                                     f"type=output")
                        
                        # 下载图像
                        image_response = requests.get(image_url)
                        image_response.raise_for_status()
                        
                        if not file_path:
                            # 默认保存路径
                            file_path = os.path.join(os.getcwd(), "temp_comfyui.png")

                        with open(file_path, 'wb') as f:
                            f.write(image_response.content)
                        
                        print(f"Image successfully generated and saved to: {os.path.abspath(file_path)}")
                        return os.path.abspath(file_path)

            except Exception as e:
                print(f"Error checking ComfyUI history/downloading image: {e}")
                
        print("Timeout or failed to retrieve image from ComfyUI history.")
        return None


    def switch_model(self, model_info: Dict[str, Any]):
        """
        对于 ComfyUI Adapter，此方法可以用来切换工作流文件，从而切换模型。
        
        Args:
            model_info (Dict[str, Any]): 预期包含 'workflow_path' 键。
        """
        new_workflow_path = model_info.get("workflow_path")
        
        if new_workflow_path and self.workflow_path != new_workflow_path:
            self.workflow_path = new_workflow_path
            try:
                self.workflow_template = self._load_workflow_template()
                print(f"ComfyUI workflow successfully switched to: {new_workflow_path}")
            except Exception:
                self.workflow_template = None
                print(f"Failed to switch ComfyUI workflow.")

# t2i_adapter.py (ComfyUI-specific Adapter)
import os
import subprocess
import base64
import copy
import json
import secrets
import threading
import time
import requests
from typing import Optional, Dict, Any

from sdk.adapters.t2i import T2IAdapter


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_size(size: Any, fallback: str) -> tuple[int, int]:
    text = str(size or fallback).strip().lower().replace(" ", "")
    try:
        width_text, height_text = text.split("x", 1)
        return max(64, int(width_text)), max(64, int(height_text))
    except Exception:
        width_text, height_text = fallback.lower().split("x", 1)
        return int(width_text), int(height_text)


def _infer_image_size(
    prompt: str,
    *,
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
    if any(marker in text for marker in ("1girl", "1boy", "portrait", "character", "角色", "人物", "立绘")):
        return portrait_size
    if any(marker in text for marker in ("landscape", "scenery", "background", "room", "street", "背景", "风景", "场景")):
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
                 auto_start: bool = False,
                 auto_size: bool = True,
                 square_size: str = "768x768",
                 portrait_size: str = "576x896",
                 landscape_size: str = "832x512",
                 size_node_id: str = "",
                 width_input_name: str = "width",
                 height_input_name: str = "height",
                 seed_node_id: str = "",
                 seed_input_name: str = "seed",
                 timeout_seconds: int = 60):
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
        self.auto_start = _coerce_bool(auto_start, False)
        self.auto_size = _coerce_bool(auto_size, True)
        self.square_size = str(square_size or "768x768")
        self.portrait_size = str(portrait_size or "576x896")
        self.landscape_size = str(landscape_size or "832x512")
        self.size_node_id = str(size_node_id or "")
        self.width_input_name = str(width_input_name or "width")
        self.height_input_name = str(height_input_name or "height")
        self.seed_node_id = str(seed_node_id or "")
        self.seed_input_name = str(seed_input_name or "seed")
        try:
            self.timeout_seconds = max(2, int(timeout_seconds))
        except Exception:
            self.timeout_seconds = 60
        self.workflow_template = self._load_workflow_template()
        if self.auto_start:
            self._start_server_process_async()

    @classmethod
    def get_config_schema(cls) -> dict[str, dict]:
        return {
            "auto_start": {
                "type": "bool",
                "label": "Auto-start ComfyUI when adapter loads",
                "default": False,
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
            "width_input_name": {
                "type": "str",
                "label": "Width input name",
                "default": "width",
            },
            "height_input_name": {
                "type": "str",
                "label": "Height input name",
                "default": "height",
            },
            "seed_node_id": {
                "type": "str",
                "label": "Optional seed node ID",
                "default": "",
            },
            "seed_input_name": {
                "type": "str",
                "label": "Seed input name",
                "default": "seed",
            },
            "timeout_seconds": {
                "type": "int",
                "label": "Generation timeout seconds",
                "default": 60,
                "min": 2,
                "max": 600,
            },
        }

    def _start_server_process_async(self):
        threading.Thread(target=self._start_server_process, daemon=True).start()

    def _start_server_process(self):
        """
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        try:
            # You might want to add a check here to see if the process is already running
            response = requests.get(self.api_url, timeout=3)
            if response.status_code == 200:
                print("ComfyUI server is already running.")
                return
        except requests.exceptions.ConnectionError:
            print("ComfyUI server not found, attempting to start...")

        if self.work_path=="":
            return

        os_path = self.work_path
        embeded_python_path = os.path.join(os_path, "python_embeded", "python.exe")
        api_path = os.path.join(os_path, "ComfyUI","main.py")
        
        # Use subprocess.Popen to start the server in the background
        subprocess.Popen([embeded_python_path, api_path], cwd=os_path)
        print("ComfyUI server starting...")

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

    def _inject_size(
        self,
        prompt_workflow: Dict[str, Any],
        prompt: str,
        explicit_size: Optional[Any] = None,
    ) -> None:
        width, height = _parse_size(
            self._resolve_size(prompt, explicit_size),
            fallback=self.square_size,
        )

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

        for node_id in candidate_ids:
            node = prompt_workflow.get(node_id)
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            node["inputs"][self.width_input_name] = width
            node["inputs"][self.height_input_name] = height

    def _inject_seed(self, prompt_workflow: Dict[str, Any], seed: Optional[Any] = None) -> None:
        try:
            seed_value = int(seed) if seed is not None else secrets.randbelow(2**48)
        except Exception:
            seed_value = secrets.randbelow(2**48)

        candidate_ids = [self.seed_node_id] if self.seed_node_id else list(prompt_workflow.keys())
        for node_id in candidate_ids:
            node = prompt_workflow.get(node_id)
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
                continue
            inputs = node["inputs"]
            if self.seed_input_name in inputs:
                inputs[self.seed_input_name] = seed_value
            elif not self.seed_node_id:
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
            prompt_workflow[self.prompt_node_id]["inputs"]["text"] = prompt
        else:
            print(f"Error: Prompt node ID '{self.prompt_node_id}' not found in workflow.")
            return None

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
            response = requests.post(
                self.api_url + self.PROMPT_ENDPOINT,
                json=payload,
                timeout=self.timeout_seconds,
            )
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
        # 简单轮询，最多等待 timeout_seconds 秒
        for _ in range(max(1, self.timeout_seconds // 2)):
            time.sleep(2)
            try:
                history_response = requests.get(
                    f"{self.api_url}{self.HISTORY_ENDPOINT}/{prompt_id}",
                    timeout=self.timeout_seconds,
                )
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
                        image_response = requests.get(
                            image_url,
                            timeout=self.timeout_seconds,
                        )
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

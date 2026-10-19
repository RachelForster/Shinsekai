"""Built-in text-to-image adapters."""
import copy
import os
import subprocess
import base64
import json
import time
import requests
import shlex
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from typing import Optional, Dict, Any

from sdk.adapters.t2i import T2IAdapter


class StableDiffusionAdapter(T2IAdapter):
    """
    Adapter for a Stable Diffusion (e.g., AUTOMATIC1111/ComfyUI) API.
    It adapts the T2I API to the standard T2IAdapter interface.
    """
    supports_reference_images = True

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

        endpoint = self.api_url
        reference = kwargs.get("reference_image_path")
        if reference:
            with open(reference, "rb") as source:
                payload["init_images"] = [base64.b64encode(source.read()).decode("ascii")]
            payload["denoising_strength"] = kwargs.get("denoising_strength", 0.65)
            if "/txt2img" not in endpoint and "/img2img" not in endpoint:
                raise ValueError("参考图需要配置 Stable Diffusion 的 /sdapi/v1/txt2img 或 /img2img 地址")
            endpoint = endpoint.replace("/txt2img", "/img2img")
        try:
            response = requests.post(endpoint, json=payload, timeout=600)
            response.raise_for_status() # Raise an exception for bad status codes

            # The response content is often a JSON object with base64 encoded images
            data = response.json()
            if not data.get("images"):
                print("Stable Diffusion API returned no images.")
                return None

            # Decode the base64 image and save it
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
    STARTUP_TIMEOUT_SECONDS = 120
    REQUEST_TIMEOUT_SECONDS = 10
    supports_reference_images = True

    @classmethod
    def get_config_schema(cls):
        return {
            "reference_node_id": {"type": "str", "default": "", "label": "参考图 LoadImage 节点 ID（单个节点时自动识别）"},
            "generation_timeout": {"type": "float", "default": 600, "label": "等待图像生成的最长秒数", "min": 1},
            "text_only_workflow_path": {"type": "str", "default": "", "label": "无参考图时使用的 API 工作流（可选）"},
            "startup_args": {"type": "str", "default": "--windows-standalone-build", "label": "ComfyUI 启动参数（端口自动匹配 API 地址）"},
            "match_reference_aspect": {"type": "bool", "default": True, "label": "H3 画布匹配参考图比例（保持像素预算）"},
        }

    def __init__(self,
                 api_url: str = "http://127.0.0.1:8188",
                 work_path: str = "",
                 workflow_path: str = "path/to/default_workflow.json",
                 prompt_node_id: str = "6", # Common ID for the CLIPTextEncode (Prompt) node in SD workflows
                 output_node_id: str = "17",
                 reference_node_id: str = "",
                 generation_timeout: float = 600,
                 text_only_workflow_path: str = "",
                 startup_args: str = "--windows-standalone-build",
                 match_reference_aspect: bool = True):
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
        self.reference_node_id = str(reference_node_id or "")
        self.generation_timeout = max(1, float(generation_timeout))
        self.text_only_workflow_path = text_only_workflow_path
        self.startup_args = startup_args
        self.match_reference_aspect = match_reference_aspect
        self.last_video_path = None
        self.last_video_frame_time = None
        self.workflow_template = self._load_workflow_template()
        self._start_server_process()

    def _is_server_ready(self) -> bool:
        try:
            response = requests.get(self.api_url, timeout=self.REQUEST_TIMEOUT_SECONDS)
            return response.status_code < 500
        except requests.exceptions.RequestException:
            return False

    def _wait_for_server_ready(self, timeout_seconds: int = STARTUP_TIMEOUT_SECONDS) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._is_server_ready():
                return True
            time.sleep(2)
        return self._is_server_ready()

    def _start_server_process(self):
        """
        Start the configured portable ComfyUI installation if it is not running.
        """
        if self._is_server_ready():
            print("ComfyUI server is already running.")
            return

        print("ComfyUI server not found, attempting to start...")

        if self.work_path=="":
            return

        os_path = self.work_path
        embeded_python_path = os.path.join(os_path, "python_embeded", "python.exe")
        api_path = os.path.join(os_path, "ComfyUI","main.py")

        # Use subprocess.Popen to start the server in the background
        port = urlsplit(self.api_url).port or 8188
        subprocess.Popen(
            [embeded_python_path, "-s", api_path, "--port", str(port), *shlex.split(self.startup_args)],
            cwd=os_path,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        print("ComfyUI server starting...")
        if self._wait_for_server_ready():
            print("ComfyUI server is ready.")
        else:
            print("ComfyUI server is still not ready after waiting.")

    def _load_workflow_template(self) -> Dict[str, Any]:
        """加载 ComfyUI 工作流 JSON 文件作为模板。"""
        try:
            with open(self.workflow_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading ComfyUI workflow template from {self.workflow_path}: {e}")
            raise

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

        self.last_video_path = None
        self.last_video_frame_time = None

        # 1. 深度复制模板以避免修改原始结构
        prompt_workflow = copy.deepcopy(self.workflow_template)
        if not kwargs.get("reference_image_path") and self.text_only_workflow_path:
            with open(self.text_only_workflow_path, encoding="utf-8-sig") as source:
                prompt_workflow = json.load(source)

        # 2. 注入主 Prompt
        # 假设 CLIPTextEncode 节点 (ID: self.prompt_node_id) 的输入是 index 1
        if self.prompt_node_id in prompt_workflow:
            inputs = prompt_workflow[self.prompt_node_id]["inputs"]
            field = "text" if "text" in inputs else "prompt" if "prompt" in inputs else None
            if field is None:
                raise ValueError("提示词节点缺少 text 或 prompt 输入，请检查 T2I 节点配置")
            inputs[field] = prompt
        else:
            raise ValueError(f"Prompt node ID '{self.prompt_node_id}' not found in workflow.")

        negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
        negative_node_id = self._find_ksampler_conditioning_node_id(prompt_workflow, "negative")
        if negative_prompt and negative_node_id:
            prompt_workflow[negative_node_id]["inputs"]["text"] = negative_prompt
        if "seed" in kwargs and kwargs["seed"] is not None:
            self._apply_sampler_seed(prompt_workflow, kwargs["seed"])
        if kwargs.get("reference_image_path"):
            self._apply_reference_image(prompt_workflow, kwargs["reference_image_path"])

        payload = {
            "prompt": prompt_workflow,
            "client_id": str(time.time()), # 简单的唯一标识符
            "extra_data": {}
        }

        try:
            if not self._wait_for_server_ready():
                raise RuntimeError(
                    "ComfyUI is still starting or is not reachable. Please wait until ComfyUI finishes loading, then retry image generation."
                )
            response = requests.post(
                self.api_url + self.PROMPT_ENDPOINT,
                json=payload,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            prompt_data = response.json()
            prompt_id = prompt_data.get("prompt_id")

            if not prompt_id:
                print("ComfyUI API failed to return a prompt_id.")
                return None

            print(f"Workflow submitted. Prompt ID: {prompt_id}. Waiting for completion...")
            return self._wait_for_and_get_image(prompt_id, file_path)

        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                "ComfyUI is not ready yet or refused the connection. Please wait until ComfyUI finishes starting, then retry image generation."
            ) from exc
        except Exception:
            raise

    def _apply_reference_image(self, workflow, path):
        candidates = [
            str(key)
            for key, node in workflow.items()
            if node.get("class_type") == "LoadImage"
        ]
        node_id = self.reference_node_id
        if not node_id and len(candidates) == 1:
            node_id = candidates[0]
        if not node_id or node_id not in candidates:
            raise ValueError(
                "参考图需要一个 LoadImage 节点；存在多个时请在 T2I 扩展配置中指定 reference_node_id"
            )
        import uuid

        canvases = set()
        h3_inputs = []
        for node in workflow.values():
            if node.get("class_type") != "MiniMaxH3ImageToVideo":
                continue
            inputs = node.get("inputs", {})
            for field in ("first_frame", "last_frame"):
                linked = inputs.get(field)
                if (
                    isinstance(linked, list)
                    and len(linked) == 2
                    and str(linked[0]) == node_id
                    and linked[1] == 0
                ):
                    width, height = inputs.get("width"), inputs.get("height")
                    if not isinstance(width, int) or not isinstance(height, int):
                        raise ValueError(
                            "请在 H3 API 工作流中用整数配置 width 和 height，以保持参考图比例"
                        )
                    canvases.add((width, height))
                    h3_inputs.append(inputs)
        if len(canvases) > 1:
            raise ValueError("同一张参考图连接的 H3 画布尺寸不同，请将画布尺寸设为一致")
        if canvases:
            from ai.t2i.reference_image import (
                fit_reference_to_canvas,
                reference_canvas_size,
            )

            width, height = next(iter(canvases))
            other_anchor = any(
                linked and linked != [node_id, 0]
                for inputs in h3_inputs
                for linked in (inputs.get("first_frame"), inputs.get("last_frame"))
            )
            if self.match_reference_aspect and not other_anchor:
                width, height = reference_canvas_size(path, width, height)
                for inputs in h3_inputs:
                    inputs.update(width=width, height=height)
            source = fit_reference_to_canvas(path, width, height)
            suffix = ".png"
        else:
            source = open(path, "rb")
            suffix = os.path.splitext(path)[1]
        with source:
            response = requests.post(
                self.api_url + "/upload/image",
                files={"image": (f"shinsekai-{uuid.uuid4().hex}{suffix}", source)},
                data={"type": "input", "overwrite": "false"},
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        uploaded = response.json()
        if not uploaded.get("name"):
            raise ValueError("ComfyUI 上传参考图失败")
        workflow[node_id]["inputs"]["image"] = "/".join(
            part for part in (uploaded.get("subfolder", ""), uploaded["name"]) if part
        )

    def _find_ksampler_conditioning_node_id(self, workflow: Dict[str, Any], input_name: str) -> str:
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "").lower()
            if "ksampler" not in class_type:
                continue
            linked = (node.get("inputs") or {}).get(input_name)
            if isinstance(linked, list) and linked:
                node_id = str(linked[0])
                target = workflow.get(node_id)
                if isinstance(target, dict) and isinstance((target.get("inputs") or {}).get("text"), str):
                    return node_id
        return ""

    @staticmethod
    def _apply_sampler_seed(workflow: Dict[str, Any], seed: Any) -> None:
        seed_value = int(seed)
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                continue
            if "noise_seed" in inputs and not isinstance(inputs["noise_seed"], list):
                inputs["noise_seed"] = seed_value
            if "seed" in inputs and not isinstance(inputs["seed"], list):
                inputs["seed"] = seed_value

    def _wait_for_and_get_image(self, prompt_id: str, file_path: Optional[str]) -> Optional[str]:
        """轮询历史记录以查找生成的图像文件。"""
        deadline = time.monotonic() + self.generation_timeout
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                history_response = requests.get(f"{self.api_url}{self.HISTORY_ENDPOINT}/{prompt_id}", timeout=self.REQUEST_TIMEOUT_SECONDS)
                history_response.raise_for_status()
                history_data = history_response.json()

                if prompt_id in history_data:
                    # 查找 SaveImage 节点的输出
                    output = history_data[prompt_id].get("outputs", {}).get(self.output_node_id)
                    status = history_data[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        raise RuntimeError("ComfyUI 工作流执行失败，请检查模型与节点配置")
                    media = next((output.get(key) for key in ("images", "videos", "gifs") if output and output.get(key)), None)
                    if status.get("completed") and not media:
                        raise ValueError("工作流未输出图片或视频，请检查 SaveImage / SaveVideo 输出节点")

                    if media:
                        image_info = media[0]
                        filename = image_info["filename"]
                        subfolder = image_info.get("subfolder", "")

                        # 构造图像下载 URL
                        image_url = f"{self.api_url}/view?" + urlencode({"filename": filename, "subfolder": subfolder, "type": image_info.get("type", "output")})

                        # 下载图像
                        image_response = requests.get(image_url, timeout=self.REQUEST_TIMEOUT_SECONDS)
                        image_response.raise_for_status()

                        if not file_path:
                            # 默认保存路径
                            file_path = os.path.join(os.getcwd(), "temp_comfyui.png")
                        destination = Path(file_path)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        suffix = Path(filename).suffix.lower()
                        is_video = suffix in {".mp4", ".webm", ".mov", ".mkv", ".avi"}
                        downloaded = destination.with_suffix(suffix) if is_video else destination
                        with open(downloaded, 'wb') as f:
                            f.write(image_response.content)

                        if is_video:
                            from core.media.video_frames import extract_video_frame

                            self.last_video_frame_time = extract_video_frame(downloaded, destination)
                            self.last_video_path = str(downloaded.resolve())

                        print(f"Image successfully generated and saved to: {os.path.abspath(file_path)}")
                        return os.path.abspath(file_path)

            except requests.exceptions.RequestException as e:
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

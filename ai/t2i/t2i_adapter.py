# t2i_adapter.py (ComfyUI-specific Adapter)
import copy
import os
import subprocess
import base64
import json
import sys
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any

from sdk.file_transactions import atomic_write_bytes, read_text_without_links
from sdk.process_launch import (
    capture_launch_directory,
    capture_launch_file,
    isolated_python_environment,
    popen_with_stable_paths,
)
from core.paths import (
    project_root,
    require_directory_without_links,
    require_regular_file_without_links,
    resolve_executable_file,
    resolve_project_output_path,
    resolve_runtime_asset_read_path,
)
from sdk.adapters.t2i import T2IAdapter


def _output_path(value: str | None, default_relative: str) -> Path:
    raw = default_relative if value is None else value
    output = resolve_project_output_path(raw, root=project_root())
    output.parent.mkdir(parents=True, exist_ok=True)
    require_directory_without_links(
        output.parent,
        field="T2I output directory",
    )
    return output


_RESOURCE_WORKFLOW_PREFIXES = (
    ("assets", "system", "workflow"),
    ("assets", "workflows"),
)


def _configured_local_path(
    value: str,
    *,
    required: bool = True,
    resource_prefixes: tuple[tuple[str, ...], ...] = (),
) -> str:
    raw = str(value or "")
    if not raw:
        if required:
            raise ValueError("configured local path is required")
        return ""
    if raw != raw.strip():
        raise ValueError("configured local path contains surrounding whitespace")
    return resolve_runtime_asset_read_path(
        raw,
        root=project_root(),
        resource_prefixes=resource_prefixes,
    ).as_posix()


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

            output = _output_path(file_path, "data/generated/temp_t2i_sd.png")
            atomic_write_bytes(output, image_data)

            return str(output)
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

    def __init__(self,
                 api_url: str = "http://127.0.0.1:8188",
                 work_path: str = "",
                 workflow_path: str = "path/to/default_workflow.json",
                 prompt_node_id: str = "6", # Common ID for the CLIPTextEncode (Prompt) node in SD workflows
                 output_node_id: str = "17"):# Common ID for the SaveImage node
        """
        初始化 ComfyUI Adapter。

        Args:
            api_url (str): ComfyUI 服务器的 API 地址 (不含 /api)。
            workflow_path (str): 预先导出的 ComfyUI 工作流 JSON 文件路径。
            prompt_node_id (str): 工作流 JSON 中用于接收文本提示的节点的 ID。
            output_node_id (str): 工作流 JSON 中用于保存或返回图像的节点的 ID (通常是 Save Image 节点)。
        """
        self.api_url = api_url.rstrip('/')
        self.workflow_path = _configured_local_path(
            workflow_path,
            resource_prefixes=_RESOURCE_WORKFLOW_PREFIXES,
        )
        self.prompt_node_id = prompt_node_id
        self.output_node_id = output_node_id
        self.work_path = _configured_local_path(work_path, required=False)
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
        Starts the GPT-SoVITS server process if it's not running.
        This is now the adapter's responsibility.
        """
        if self._is_server_ready():
            print("ComfyUI server is already running.")
            return

        print("ComfyUI server not found, attempting to start...")

        if self.work_path == "":
            return

        os_path = require_directory_without_links(
            self.work_path,
            field="ComfyUI work directory",
        )
        work_snapshot = capture_launch_directory(
            os_path,
            field="ComfyUI work directory",
        )
        script_candidates = (
            os_path / "ComfyUI" / "main.py",
            os_path / "main.py",
        )
        api_path = next(
            (
                require_regular_file_without_links(
                    path,
                    field="ComfyUI startup script",
                )
                for path in script_candidates
                if os.path.lexists(path)
            ),
            None,
        )
        if api_path is None:
            raise FileNotFoundError(f"ComfyUI main.py not found under: {os_path}")

        if os.name == "nt":
            python_candidates = (
                os_path / "python_embeded" / "python.exe",
                os_path / ".venv" / "Scripts" / "python.exe",
                os_path / "venv" / "Scripts" / "python.exe",
            )
        else:
            python_candidates = (
                os_path / ".venv" / "bin" / "python",
                os_path / "venv" / "bin" / "python",
            )
        python_path = next(
            (
                resolve_executable_file(
                    path,
                    field="ComfyUI Python executable",
                )
                for path in python_candidates
                if os.path.lexists(path)
            ),
            None,
        )
        if python_path is None:
            if getattr(sys, "frozen", False):
                raise FileNotFoundError(
                    f"ComfyUI Python executable not found under: {os_path}"
                )
            python_path = resolve_executable_file(
                Path(sys.executable),
                field="host Python executable",
            )

        python_snapshot = capture_launch_file(
            python_path,
            field="ComfyUI Python executable",
            executable=True,
        )
        script_snapshot = capture_launch_file(
            api_path,
            field="ComfyUI startup script",
        )
        popen_with_stable_paths(
            [python_snapshot.path, script_snapshot.path],
            cwd=work_snapshot,
            executable=python_snapshot,
            required_files=(script_snapshot,),
            env=isolated_python_environment(),
            popen_factory=subprocess.Popen,
        )
        print("ComfyUI server starting...")
        if self._wait_for_server_ready():
            print("ComfyUI server is ready.")
        else:
            print("ComfyUI server is still not ready after waiting.")

    def _load_workflow_template(self) -> Dict[str, Any]:
        """加载 ComfyUI 工作流 JSON 文件作为模板。"""
        try:
            return json.loads(read_text_without_links(self.workflow_path))
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

        # 1. 深度复制模板以避免修改原始结构
        prompt_workflow = copy.deepcopy(self.workflow_template)

        # 2. 注入主 Prompt
        # 假设 CLIPTextEncode 节点 (ID: self.prompt_node_id) 的输入是 index 1
        if self.prompt_node_id in prompt_workflow:
            prompt_workflow[self.prompt_node_id]["inputs"]["text"] = prompt
        else:
            raise ValueError(f"Prompt node ID '{self.prompt_node_id}' not found in workflow.")

        negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
        negative_node_id = self._find_ksampler_conditioning_node_id(prompt_workflow, "negative")
        if negative_prompt and negative_node_id:
            prompt_workflow[negative_node_id]["inputs"]["text"] = negative_prompt
        if "seed" in kwargs and kwargs["seed"] is not None:
            self._apply_sampler_seed(prompt_workflow, kwargs["seed"])

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
            class_type = str(node.get("class_type") or "").lower()
            if "ksampler" not in class_type and "sampler" not in class_type:
                continue
            inputs = node.setdefault("inputs", {})
            if not isinstance(inputs, dict):
                continue
            if "noise_seed" in inputs:
                inputs["noise_seed"] = seed_value
            if "seed" in inputs or "ksampler" in class_type:
                inputs["seed"] = seed_value

    def _wait_for_and_get_image(self, prompt_id: str, file_path: Optional[str]) -> Optional[str]:
        """轮询历史记录以查找生成的图像文件。"""
        # 简单轮询，最多等待 60 秒
        for _ in range(30):
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

                        output = _output_path(file_path, "data/generated/temp_comfyui.png")
                        atomic_write_bytes(output, image_response.content)

                        print(f"Image successfully generated and saved to: {output}")
                        return str(output)

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

        if new_workflow_path:
            resolved_workflow_path = _configured_local_path(
                str(new_workflow_path),
                resource_prefixes=_RESOURCE_WORKFLOW_PREFIXES,
            )
        else:
            return

        if self.workflow_path != resolved_workflow_path:
            previous_path = self.workflow_path
            previous_template = self.workflow_template
            self.workflow_path = resolved_workflow_path
            try:
                self.workflow_template = self._load_workflow_template()
                print(f"ComfyUI workflow successfully switched to: {resolved_workflow_path}")
            except Exception:
                self.workflow_path = previous_path
                self.workflow_template = previous_template
                print(f"Failed to switch ComfyUI workflow.")

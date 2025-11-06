# t2i_adapter.py (ComfyUI-specific Adapter)
import os
import requests
import base64
import json
import time
from typing import Optional, Dict, Any

# Assuming T2IAdapter ABC is defined here
# t2i_adapter.py
from abc import ABC, abstractmethod
import os
import requests
from typing import Optional, Dict, Any
import subprocess

class T2IAdapter(ABC):
    """
    Abstract Adapter for Text-to-Image (T2I) services.
    This defines the standard interface that all T2I adapters must implement.
    """
    @abstractmethod
    def generate_image(self, prompt: str, file_path: Optional[str] = None, **kwargs) -> Optional[str]:
        """Generates an image from a text prompt and returns the file path."""
        pass

    @abstractmethod
    def switch_model(self, model_info: Dict[str, Any]):
        """Switches the T2I model or configuration."""
        pass

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
        self.workflow_path = workflow_path
        self.prompt_node_id = prompt_node_id
        self.output_node_id = output_node_id
        self.work_path = work_path
        self.workflow_template = self._load_workflow_template()
        self._start_server_process()

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
        prompt_workflow = self.workflow_template.copy()
        
        # 2. 注入主 Prompt
        # 假设 CLIPTextEncode 节点 (ID: self.prompt_node_id) 的输入是 index 1
        if self.prompt_node_id in prompt_workflow:
            prompt_workflow[self.prompt_node_id]["inputs"]["text"] = prompt
        else:
            print(f"Error: Prompt node ID '{self.prompt_node_id}' not found in workflow.")
            return None

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
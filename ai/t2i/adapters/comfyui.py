"""ComfyUI text-to-image workflow adapter."""

from __future__ import annotations

import copy
import ipaddress
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlsplit

import requests

from ai.t2i.comfyui_connection import probe_comfyui_connection
from ai.t2i.comfyui_workflow import (
    apply_sampler_seed,
    find_ksampler_conditioning_node_id,
    read_api_workflow,
)
from core.adapters import builtin_adapter
from sdk.adapters.t2i import T2IAdapter


@builtin_adapter("comfyui", label="ComfyUI", order=10)
class ComfyUIT2IAdapter(T2IAdapter):
    """Adapter for the ComfyUI Text-to-Image service API."""

    # ------------------ ComfyUI API Endpoints ------------------
    # NOTE: You must have a ComfyUI instance running with the API enabled.
    PROMPT_ENDPOINT = "/prompt"
    HISTORY_ENDPOINT = "/history"
    STARTUP_TIMEOUT_SECONDS = 120
    REQUEST_TIMEOUT_SECONDS = 10
    supports_reference_images = True

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "auto_start": {
                "type": "bool",
                "default": False,
                "label": "由新世界自动启动官方 Windows 便携版",
            },
            "reference_node_id": {
                "type": "str",
                "default": "",
                "label": "参考图 LoadImage 节点 ID（单个节点时自动识别）",
            },
            "generation_timeout": {
                "type": "float",
                "default": 600,
                "label": "等待图像生成的最长秒数",
                "min": 1,
            },
            "text_only_workflow_path": {
                "type": "str",
                "default": "",
                "label": "无参考图时使用的 API 工作流（可选）",
            },
            "startup_args": {
                "type": "str",
                "default": "--windows-standalone-build",
                "label": "ComfyUI 启动参数（端口自动匹配 API 地址）",
            },
            "match_reference_aspect": {
                "type": "bool",
                "default": True,
                "label": "H3 画布匹配参考图比例（保持像素预算）",
            },
        }

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8188",
        work_path: str = "",
        workflow_path: str = "path/to/default_workflow.json",
        prompt_node_id: str = "6",
        output_node_id: str = "17",
        reference_node_id: str = "",
        generation_timeout: float = 600,
        text_only_workflow_path: str = "",
        startup_args: str = "--windows-standalone-build",
        match_reference_aspect: bool = True,
        auto_start: Optional[bool] = None,
    ) -> None:
        self.api_url = api_url.strip().rstrip("/")
        self.workflow_path = workflow_path
        self.prompt_node_id = prompt_node_id
        self.output_node_id = output_node_id
        self.work_path = work_path
        # Preserve existing portable installations; new configurations opt in explicitly.
        self.auto_start = bool(work_path.strip()) if auto_start is None else auto_start
        self.reference_node_id = str(reference_node_id or "")
        self.generation_timeout = max(1, float(generation_timeout))
        self.text_only_workflow_path = text_only_workflow_path
        self.startup_args = startup_args
        self.match_reference_aspect = match_reference_aspect
        self.last_video_path: Optional[str] = None
        self.last_video_frame_time: Any = None
        self.workflow_template = self._load_workflow_template()
        self._start_server_process()

    def _is_server_ready(self) -> bool:
        return probe_comfyui_connection(
            self.api_url, timeout=self.REQUEST_TIMEOUT_SECONDS
        )["ok"]

    def _wait_for_server_ready(
        self, timeout_seconds: int = STARTUP_TIMEOUT_SECONDS
    ) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._is_server_ready():
                return True
            time.sleep(2)
        return self._is_server_ready()

    def _start_server_process(self) -> None:
        """Start the configured portable ComfyUI installation if it is not running."""
        if self._is_server_ready():
            print("ComfyUI server is already running.")
            return

        if not getattr(self, "auto_start", bool(self.work_path.strip())):
            raise RuntimeError(
                "无法连接 ComfyUI API。请先用秋叶／绘世等自带启动器或原有方式启动 ComfyUI，"
                "等待网页可用，再将相同的服务根地址（含实际端口，不含 /prompt）填入 API 设定。"
                "整合包无需填写 ComfyUI 目录，也无需开启自动启动。"
            )

        host = urlsplit(self.api_url).hostname or ""
        try:
            local = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            raise ValueError(
                "自动启动仅支持本机 ComfyUI；连接其他电脑时请关闭自动启动并在服务端启动 ComfyUI。"
            )

        os_path = self.work_path
        embeded_python_path = os.path.join(os_path, "python_embeded", "python.exe")
        api_path = os.path.join(os_path, "ComfyUI", "main.py")
        if not os.path.isfile(embeded_python_path) or not os.path.isfile(api_path):
            raise ValueError(
                "自动启动目录必须是官方 Windows 便携版根目录，包含 python_embeded/python.exe "
                "和 ComfyUI/main.py。秋叶／绘世、桌面版或其他安装方式请关闭自动启动，"
                "使用自己的启动器启动后连接。"
            )

        port = urlsplit(self.api_url).port or 8188
        subprocess.Popen(
            [
                embeded_python_path,
                "-s",
                api_path,
                "--port",
                str(port),
                *shlex.split(self.startup_args),
            ],
            cwd=os_path,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        print("ComfyUI server starting...")
        if self._wait_for_server_ready():
            print("ComfyUI server is ready.")
        else:
            raise RuntimeError(
                "ComfyUI 启动后仍无法连接 API，请检查 ComfyUI 启动日志和 API 地址中的端口。"
            )

    def _load_workflow_template(self) -> Dict[str, Any]:
        """加载 ComfyUI 工作流 JSON 文件作为模板。"""
        return self._read_api_workflow(self.workflow_path)

    @staticmethod
    def _read_api_workflow(path: str) -> Dict[str, Any]:
        return read_api_workflow(path)

    def generate_image(
        self,
        prompt: str,
        file_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """生成图像。通过修改工作流中的 prompt 节点并提交执行。"""
        if not self.workflow_template:
            return None

        self.last_video_path = None
        self.last_video_frame_time = None
        self._video_frame_fraction = 0.5

        prompt_workflow = copy.deepcopy(self.workflow_template)
        if not kwargs.get("reference_image_path") and self.text_only_workflow_path:
            prompt_workflow = self._read_api_workflow(self.text_only_workflow_path)
        if kwargs.get("h3_static_sprite"):
            from ai.t2i.reference_image import apply_h3_sprite_resolution

            apply_h3_sprite_resolution(
                prompt_workflow, kwargs.get("h3_resolution", "workflow")
            )
            h3_nodes = [
                node
                for node in prompt_workflow.values()
                if node.get("class_type") == "MiniMaxH3ImageToVideo"
            ]
            # Keep custom guide timelines and linked lengths intact. The bundled
            # I2V/T2V graphs can use a short 17k+5 clip when only a still is needed.
            has_guides = any(
                node.get("class_type") == "MiniMaxH3AddGuide"
                for node in prompt_workflow.values()
            )
            lengths = [node.get("inputs", {}).get("length", 124) for node in h3_nodes]
            if (
                h3_nodes
                and not has_guides
                and all(
                    isinstance(length, int) and not isinstance(length, bool) and length >= 5
                    for length in lengths
                )
            ):
                for node, length in zip(h3_nodes, lengths):
                    node["inputs"]["length"] = min(length, 39)
                self._video_frame_fraction = 0.8

        if self.prompt_node_id in prompt_workflow:
            inputs = prompt_workflow[self.prompt_node_id]["inputs"]
            field = "text" if "text" in inputs else "prompt" if "prompt" in inputs else None
            if field is None:
                raise ValueError("提示词节点缺少 text 或 prompt 输入，请检查 T2I 节点配置")
            inputs[field] = prompt
        else:
            raise ValueError(f"Prompt node ID '{self.prompt_node_id}' not found in workflow.")

        negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
        negative_node_id = self._find_ksampler_conditioning_node_id(
            prompt_workflow, "negative"
        )
        if negative_prompt and negative_node_id:
            prompt_workflow[negative_node_id]["inputs"]["text"] = negative_prompt
        if "seed" in kwargs and kwargs["seed"] is not None:
            self._apply_sampler_seed(prompt_workflow, kwargs["seed"])
        if kwargs.get("reference_image_path"):
            self._apply_reference_image(
                prompt_workflow,
                kwargs["reference_image_path"],
                background=kwargs.get("reference_background_color", "white"),
            )
        if kwargs.get("last_reference_image_path"):
            self._apply_reference_image(
                prompt_workflow,
                kwargs["last_reference_image_path"],
                node_id="shinsekai_last_frame",
                background=kwargs.get("reference_background_color", "white"),
            )

        payload = {
            "prompt": prompt_workflow,
            "client_id": str(time.time()),
            "extra_data": {},
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

    def _apply_reference_image(
        self,
        workflow: Dict[str, Any],
        path: str,
        node_id: Optional[str] = None,
        background: str = "white",
    ) -> None:
        candidates = [
            str(key)
            for key, node in workflow.items()
            if node.get("class_type") == "LoadImage"
        ]
        node_id = node_id or self.reference_node_id
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
            source = fit_reference_to_canvas(path, width, height, background=background)
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

    def _find_ksampler_conditioning_node_id(
        self, workflow: Dict[str, Any], input_name: str
    ) -> str:
        return find_ksampler_conditioning_node_id(workflow, input_name)

    @staticmethod
    def _apply_sampler_seed(workflow: Dict[str, Any], seed: Any) -> None:
        apply_sampler_seed(workflow, seed)

    def _wait_for_and_get_image(
        self, prompt_id: str, file_path: Optional[str]
    ) -> Optional[str]:
        """轮询历史记录以查找生成的图像文件。"""
        deadline = time.monotonic() + self.generation_timeout
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                history_response = requests.get(
                    f"{self.api_url}{self.HISTORY_ENDPOINT}/{prompt_id}",
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
                history_response.raise_for_status()
                history_data = history_response.json()

                if prompt_id in history_data:
                    output = history_data[prompt_id].get("outputs", {}).get(
                        self.output_node_id
                    )
                    status = history_data[prompt_id].get("status", {})
                    if status.get("status_str") == "error":
                        raise RuntimeError("ComfyUI 工作流执行失败，请检查模型与节点配置")
                    media = next(
                        (
                            output.get(key)
                            for key in ("images", "videos", "gifs")
                            if output and output.get(key)
                        ),
                        None,
                    )
                    if status.get("completed") and not media:
                        raise ValueError(
                            "工作流未输出图片或视频，请检查 SaveImage / SaveVideo 输出节点"
                        )

                    if media:
                        image_info = media[0]
                        filename = image_info["filename"]
                        subfolder = image_info.get("subfolder", "")

                        image_url = f"{self.api_url}/view?" + urlencode(
                            {
                                "filename": filename,
                                "subfolder": subfolder,
                                "type": image_info.get("type", "output"),
                            }
                        )

                        image_response = requests.get(
                            image_url, timeout=self.REQUEST_TIMEOUT_SECONDS
                        )
                        image_response.raise_for_status()

                        if not file_path:
                            file_path = os.path.join(os.getcwd(), "temp_comfyui.png")
                        destination = Path(file_path)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        suffix = Path(filename).suffix.lower()
                        is_video = suffix in {".mp4", ".webm", ".mov", ".mkv", ".avi"}
                        downloaded = (
                            destination.with_suffix(suffix) if is_video else destination
                        )
                        with open(downloaded, "wb") as f:
                            f.write(image_response.content)

                        if is_video:
                            from core.media.video_frames import extract_video_frame

                            self.last_video_frame_time = extract_video_frame(
                                downloaded,
                                destination,
                                fraction=getattr(self, "_video_frame_fraction", 0.5),
                            )
                            self.last_video_path = str(downloaded.resolve())

                        print(
                            f"Image successfully generated and saved to: {os.path.abspath(file_path)}"
                        )
                        return os.path.abspath(file_path)

            except requests.exceptions.RequestException as e:
                print(f"Error checking ComfyUI history/downloading image: {e}")

        print("Timeout or failed to retrieve image from ComfyUI history.")
        return None

    def switch_model(self, model_info: Dict[str, Any]) -> None:
        """对于 ComfyUI Adapter，此方法可以用来切换工作流文件，从而切换模型。"""
        new_workflow_path = model_info.get("workflow_path")

        if new_workflow_path and self.workflow_path != new_workflow_path:
            self.workflow_path = new_workflow_path
            try:
                self.workflow_template = self._load_workflow_template()
                print(f"ComfyUI workflow successfully switched to: {new_workflow_path}")
            except Exception:
                self.workflow_template = None
                print("Failed to switch ComfyUI workflow.")

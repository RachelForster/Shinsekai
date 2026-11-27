"""Kaggle-hosted GPT-SoVITS tunnel TTS adapter."""

from __future__ import annotations

from typing import Any

from ai.tts.adapters.gpt_sovits import GPTSoVitsAdapter
from core.adapters import builtin_adapter
from sdk.logging import get_logger

logger = get_logger(__name__)


def is_kaggle_path(path: str) -> bool:
    """Return ``True`` when ``path`` points inside ``/kaggle/``."""
    return str(path or "").strip().startswith("/kaggle/")


@builtin_adapter("kaggle-gpt-sovits", label="Kaggle GPT-SoVITS", order=20)
class KaggleGPTSoVitsAdapter(GPTSoVitsAdapter):
    """GPT-SoVITS adapter for a Kaggle-hosted API.

    Kaggle cannot read local Shinsekai paths like ``data/models/...``. By
    default this adapter assumes the notebook has already loaded the selected
    character model and only sends synthesis requests. Optional ``/kaggle/...``
    paths can be configured when explicit weight switching is needed.
    """

    def __init__(
        self,
        tts_server_url: str = "http://127.0.0.1:9880/",
        gpt_sovits_work_path: str | None = None,
        remote_gpt_model_path: str = "",
        remote_sovits_model_path: str = "",
        remote_ref_audio_path: str = "/kaggle/working/shinsekai_ref_clean.wav",
        switch_weights: bool = False,
        text_split_method: str = "cut5",
        batch_size: int = 4,
        speed_factor: float = 1.0,
        use_character_speed: bool = False,
        parallel_infer: bool = True,
        split_bucket: bool = True,
        batch_threshold: float = 0.75,
        super_sampling: bool = False,
    ) -> None:
        self.remote_gpt_model_path = str(remote_gpt_model_path or "").strip()
        self.remote_sovits_model_path = str(remote_sovits_model_path or "").strip()
        self.remote_ref_audio_path = str(remote_ref_audio_path or "").strip()
        self.switch_weights = bool(switch_weights)
        self.text_split_method = str(text_split_method or "cut5").strip() or "cut5"
        try:
            self.batch_size = max(1, int(batch_size))
        except (TypeError, ValueError):
            self.batch_size = 4
        try:
            self.speed_factor = float(speed_factor)
        except (TypeError, ValueError):
            self.speed_factor = 1.0
        self.use_character_speed = bool(use_character_speed)
        self.parallel_infer = bool(parallel_infer)
        self.split_bucket = bool(split_bucket)
        try:
            self.batch_threshold = float(batch_threshold)
        except (TypeError, ValueError):
            self.batch_threshold = 0.75
        self.super_sampling = bool(super_sampling)
        super().__init__(tts_server_url=tts_server_url, gpt_sovits_work_path=None)

    @classmethod
    def get_config_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "remote_ref_audio_path": {
                "label": "Kaggle 参考音频路径",
                "type": "str",
                "default": "/kaggle/working/shinsekai_ref_clean.wav",
            },
            "switch_weights": {
                "label": "每次角色切换时请求 Kaggle 切权重",
                "type": "bool",
                "default": False,
            },
            "remote_gpt_model_path": {
                "label": "Kaggle GPT 模型路径",
                "type": "str",
                "default": "",
            },
            "remote_sovits_model_path": {
                "label": "Kaggle SoVITS 模型路径",
                "type": "str",
                "default": "",
            },
            "text_split_method": {
                "label": "GPT-SoVITS 分句方式",
                "type": "str",
                "default": "cut5",
            },
            "batch_size": {
                "label": "推理 batch_size（长文本可提速，OOM 降到 1）",
                "type": "int",
                "default": 4,
                "min": 1,
                "max": 16,
            },
            "speed_factor": {
                "label": "固定语速倍率（1.0 最快且最稳）",
                "type": "float",
                "default": 1.0,
                "min": 0.5,
                "max": 2.0,
                "step": 0.05,
            },
            "use_character_speed": {
                "label": "使用角色 speech_speed（可能降低推理速度）",
                "type": "bool",
                "default": False,
            },
            "parallel_infer": {
                "label": "开启 parallel_infer",
                "type": "bool",
                "default": True,
            },
            "split_bucket": {
                "label": "开启 split_bucket",
                "type": "bool",
                "default": True,
            },
            "batch_threshold": {
                "label": "batch_threshold",
                "type": "float",
                "default": 0.75,
                "min": 0.1,
                "max": 1.0,
                "step": 0.05,
            },
            "super_sampling": {
                "label": "开启 super_sampling（更慢）",
                "type": "bool",
                "default": False,
            },
        }

    def _start_server_process(self) -> None:
        if self._server_is_reachable():
            logger.info("Kaggle GPT-SoVITS server is reachable.")
        else:
            logger.info(
                "Kaggle GPT-SoVITS server is not reachable; start the Kaggle notebook and tunnel first."
            )

    def _configured_or_kaggle_path(self, configured: str, fallback: str) -> str:
        cleaned_configured = str(configured or "").strip()
        cleaned_fallback = str(fallback or "").strip()
        if cleaned_configured:
            return cleaned_configured
        if is_kaggle_path(cleaned_fallback):
            return cleaned_fallback
        return ""

    def switch_model(self, model_info: dict[str, Any] | None) -> None:
        if not self.switch_weights:
            logger.debug(
                "Kaggle GPT-SoVITS: skip weight switch; using the model currently loaded in Kaggle."
            )
            return

        model_info = model_info or {}
        gpt_model_path = self._configured_or_kaggle_path(
            self.remote_gpt_model_path,
            model_info.get("gpt_model_path", ""),
        )
        sovits_model_path = self._configured_or_kaggle_path(
            self.remote_sovits_model_path,
            model_info.get("sovits_model_path", ""),
        )
        if not gpt_model_path or not sovits_model_path:
            raise RuntimeError(
                "Kaggle GPT-SoVITS weight switch requires /kaggle/... model paths. "
                "Fill the Kaggle GPT/SoVITS paths in adapter extras, or disable switch_weights."
            )
        super().switch_model(
            {
                "gpt_model_path": gpt_model_path,
                "sovits_model_path": sovits_model_path,
            }
        )

    def generate_speech(self, text: str, file_path: str | None = None, **kwargs: Any) -> str | None:
        call_kwargs = dict(kwargs)
        ref_audio_path = self._configured_or_kaggle_path(
            self.remote_ref_audio_path,
            call_kwargs.get("ref_audio_path", ""),
        )
        if not ref_audio_path:
            logger.warning(
                "Kaggle GPT-SoVITS requires a /kaggle/... reference audio path; "
                "fill remote_ref_audio_path in the TTS extra settings."
            )
            return None
        call_kwargs["ref_audio_path"] = ref_audio_path
        call_kwargs["text_split_method"] = self.text_split_method
        call_kwargs["batch_size"] = self.batch_size
        call_kwargs["speed_factor"] = (
            call_kwargs.get("speed_factor")
            if self.use_character_speed
            else self.speed_factor
        )
        if call_kwargs["speed_factor"] is None:
            call_kwargs["speed_factor"] = self.speed_factor
        call_kwargs["parallel_infer"] = self.parallel_infer
        call_kwargs["split_bucket"] = self.split_bucket
        call_kwargs["batch_threshold"] = self.batch_threshold
        call_kwargs["super_sampling"] = self.super_sampling
        return super().generate_speech(text, file_path=file_path, **call_kwargs)

"""
Moondream 视屏能力暴露给 LLM 的 function-calling 工具。

模块被 ``plugin`` 导入时登记到 :mod:`sdk.tool_registry`；
宿主在 ``ensure_plugins_loaded`` 时统一注入 :class:`~llm.tools.tool_manager.ToolManager`。
"""

from __future__ import annotations

import logging
from typing import Any

from sdk.tool_registry import tool

logger = logging.getLogger(__name__)


@tool(
    name="moondream_query_screen",
    description=(
        "Capture the given monitor and answer your question using the local Moondream2 vision model. "
        "Use when the user needs on-screen facts (UI text, errors, URLs, window contents). "
        "Pass question: a clear instruction in English, e.g. 'What error text is shown in the dialog?' "
        "Optional monitor_index: mss monitor index; default -1 uses the plugin setting; 0 = virtual full desktop, 1 = primary."
    ),
)
def moondream_query_screen(question: str, monitor_index: int = -1) -> dict[str, Any]:
    """
    Answer ``question`` from a fresh screenshot (English instructions work best).
    """
    q = (question or "").strip()
    if not q:
        return {"error": "question must not be empty: say what to read from the screen (English recommended)."}

    try:
        from plugins.moondream_vision.capture_infer import grab_screen_png
        from plugins.moondream_vision.config_model import load_config
        from plugins.moondream_vision.local_infer import infer_screen_png
        from plugins.moondream_vision import runtime
    except ImportError as e:
        return {"error": f"Moondream 插件依赖未就绪: {e}"}

    try:
        cfg_path = runtime.plugin_config_path()
    except RuntimeError:
        return {
            "error": "Moondream 尚未完成初始化。请先启动主程序并确保 Moondream 识屏插件已加载。",
        }

    cfg = load_config(cfg_path)
    mi = int(monitor_index)
    if mi >= 0:
        cfg.monitor_index = mi
    cfg.clamp()

    try:
        from plugins.moondream_vision.ui_busy import moondream_busy

        with moondream_busy():
            png = grab_screen_png(cfg.monitor_index)
            text = infer_screen_png(png, q, cfg)
    except Exception as e:
        logger.exception("moondream_query_screen 推理失败")
        return {"error": str(e)}

    return {
        "answer": text,
        "monitor_index": int(cfg.monitor_index),
    }

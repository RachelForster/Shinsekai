"""API 设定标签页。"""

import gradio as gr

from llm.constants import LLM_BASE_URLS
from ui.webui.context import WebUIContext


def register_api_tab(ctx: WebUIContext) -> None:
    with gr.Tab("API 设定"):
        gr.Markdown("## API 配置")
        with gr.Row():
            with gr.Column():
                _provider, _model, _base_url, _api_key = ctx.config_manager.get_llm_api_config()
                _is_streaming = "是" if ctx.config_manager.config.api_config.is_streaming else "否"
                gr.Markdown("### LLM API 配置")
                llm_provider = gr.Dropdown(
                    choices=list(LLM_BASE_URLS.keys()),
                    label="选择大语言模型供应商",
                    value=_provider,
                )
                llm_model = gr.Textbox(label="模型ID", value=_model)
                api_key = gr.Textbox(label="LLM API Key", type="password", value=_api_key)
                base_url = gr.Textbox(label="LLM API 基础网址", value=_base_url)
                is_streaming = gr.Radio(label="是否使用流式响应", choices=["是", "否"], value=_is_streaming)
                with gr.Accordion("高级LLM设置", open=False):
                    gr.Markdown(
                        "说明：OpenAI/Deepseek/豆包/通义千问通常支持 temperature、presence_penalty、frequency_penalty；"
                        "Claude 仅使用 temperature；Gemini 通过 OpenAI 兼容接口时按兼容能力处理。"
                        "repetition_penalty 并非所有 provider 支持，不支持时会自动忽略。"
                    )
                    temperature = gr.Slider(
                        minimum=0.0,
                        maximum=2.0,
                        value=float(ctx.config_manager.config.api_config.temperature),
                        step=0.05,
                        label="temperature",
                    )
                    repetition_penalty = gr.Slider(
                        minimum=0.5,
                        maximum=2.0,
                        value=float(ctx.config_manager.config.api_config.repetition_penalty),
                        step=0.05,
                        label="repetition_penalty",
                    )
                    presence_penalty = gr.Slider(
                        minimum=-2.0,
                        maximum=2.0,
                        value=float(ctx.config_manager.config.api_config.presence_penalty),
                        step=0.05,
                        label="presence_penalty",
                    )
                    frequency_penalty = gr.Slider(
                        minimum=-2.0,
                        maximum=2.0,
                        value=float(ctx.config_manager.config.api_config.frequency_penalty),
                        step=0.05,
                        label="frequency_penalty",
                    )
                    max_context_tokens = gr.Number(
                        label="最大上下文 token",
                        value=int(ctx.config_manager.config.api_config.max_context_tokens),
                        precision=0,
                    )
            with gr.Column():
                api_output = gr.Textbox(label="输出信息", interactive=False)
        with gr.Row():
            with gr.Column():
                _gsv_url, _gpt_sovits_work_path, _tts_provider = ctx.config_manager.get_gpt_sovits_config()
                gr.Markdown("### TTS API 配置，如果没有可以不填，如果你想让角色读出台词，就需要配置")
                gr.Markdown("说明：Genie TTS 适用于 CPU；GPT SoVITS 更依赖 GPU 性能。选择「不使用」则不加载语音合成。")
                _tts_choices = ["不使用", "Genie TTS", "GPT SoVITS"]
                if _tts_provider == "none":
                    _tts_val = "不使用"
                elif _tts_provider == "genie-tts":
                    _tts_val = "Genie TTS"
                else:
                    _tts_val = "GPT SoVITS"
                tts_provider = gr.Dropdown(
                    choices=_tts_choices,
                    label="TTS 引擎",
                    value=_tts_val,
                )
                gr.Markdown("#### 前提条件")
                gr.Markdown(
                    """
                1. 如果选择GPT SoVITS，你的GPU需要大于等于6G，如果选择Genie TTS就不需要
                2. 下载好对应的TTS引擎整合包
                """
                )

                sovits_url = gr.Textbox(label="TTS引擎 API 调用地址", value=_gsv_url)
                gpt_sovits_api_path = gr.Textbox(label="TTS引擎 服务启动路径", value=_gpt_sovits_work_path)
                t2i_provider = gr.Textbox(
                    label="",
                    value=ctx.config_manager.config.api_config.t2i_provider or "comfyui",
                    visible=False,
                )

                gr.Markdown("### ComfyUI 配置")
                with gr.Accordion("如果没有可以不填，这是用来生成CG的", open=False):
                    t2i_url = gr.Textbox(
                        label="ComfyUI API 调用地址", value=ctx.config_manager.config.api_config.t2i_api_url
                    )
                    t2i_work_path = gr.Textbox(
                        label="ComfyUI 安装路径", value=ctx.config_manager.config.api_config.t2i_work_path
                    )
                    t2i_default_workflow_path = gr.Textbox(
                        label="ComfyUI 默认工作流路径（需要导出生API格式的json文件）",
                        value=ctx.config_manager.config.api_config.t2i_default_workflow_path,
                    )
                    prompt_node_id = gr.Textbox(
                        label="输入节点ID", value=ctx.config_manager.config.api_config.t2i_prompt_node_id
                    )
                    output_node_id = gr.Textbox(
                        label="保存节点ID", value=ctx.config_manager.config.api_config.t2i_output_node_id
                    )
                save_api_btn = gr.Button("保存配置")
            with gr.Column():
                gr.Markdown("### 下载GPT SOVITS整合包")
                gr.HTML(
                    """
                 <a href="https://github.com/RVC-Boss/GPT-SoVITS"
                       download="GPT-SoVITS-v2pro-20250604.7z"
                       style="display: inline-block; padding: 12px 24px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 16px; margin-top: 10px;">
                       GPT-SOVITS github 源地址
                    </a>
                 <a href="https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604.7z"
                       download="GPT-SoVITS-v2pro-20250604.7z"
                       style="display: inline-block; padding: 12px 24px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 16px; margin-top: 10px;">
                       点击下载GPT-SOVITS整合包
                    </a>
                    <a href="https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/GPT-SoVITS-v2pro-20250604-nvidia50.7z"
                       download="GPT-SoVITS-v2pro-20250604-50x0.7z"
                       style="display: inline-block; padding: 12px 24px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; font-size: 16px; margin-top: 10px;">
                       点击下载GPT-SOVITS整合包（50系显卡适用）
                    </a>
                """
                )
                with gr.Accordion("使用说明", open=False):
                    gr.Markdown(
                        """
                    如果你选择GPT SoVITS，则需要下载GPT-SOVITS整合包。
                    如果你选择Genie TTS，则需要下载Genie TTS整合包。
                    ### 解压和使用步骤:
                    1. 下载完成后，使用7-Zip或类似工具解压文件
                    2. 将解压后的文件夹目录填写 TTS引擎 服务启动路径中

                    ### 注意事项:
                    - 如果选择GPT SoVITS，则需要确保有足够的磁盘空间(至少11GB可用空间)
                    - 如果选择Genie TTS，则需要4GB以上的可用磁盘空间
                    - 建议使用稳定的网络环境下载
                    - 如遇下载问题，请检查网络连接或稍后重试
                    """
                    )
        llm_provider.change(
            ctx.config_manager.update_llm_info,
            inputs=llm_provider,
            outputs=[base_url, llm_model, api_key],
        )

        save_api_btn.click(
            ctx.config_manager.save_api_config_new,
            inputs=[
                llm_provider,
                llm_model,
                api_key,
                base_url,
                is_streaming,
                tts_provider,
                sovits_url,
                gpt_sovits_api_path,
                t2i_provider,
                t2i_url,
                t2i_work_path,
                t2i_default_workflow_path,
                prompt_node_id,
                output_node_id,
                temperature,
                repetition_penalty,
                presence_penalty,
                frequency_penalty,
                max_context_tokens,
            ],
            outputs=api_output,
        )

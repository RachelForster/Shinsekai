"""音乐翻唱流水线 Gradio 标签页。"""

from __future__ import annotations

import traceback

import gradio as gr

from live.music_cover_pipeline import format_pipeline_log, run_pipeline, search_preview
from ui.webui.context import WebUIContext


def register_music_cover_tab(ctx: WebUIContext) -> None:
    config_manager = ctx.config_manager
    """在 `gr.Blocks` 上下文中调用，注册「音乐翻唱流水线」标签页。"""
    with gr.Tab("音乐翻唱流水线"):
        gr.Markdown(
            "## 下载 → 歌词/字幕 → UVR 分离 → RVC 翻唱 → 合成\n"
            "- **来源**：YouTube 搜索、Bilibili（中国站视频/音频）搜索，或直接粘贴完整 URL（支持 yt-dlp 支持的站点）。\n"
            "- **字幕**：下载阶段由 yt-dlp 尽量抓取字幕/自动字幕（vtt/srt），与时间轴一并保存在任务目录。\n"
            "- **人声分离**：配置 UVR（或其它）命令模板；若留空可安装 `audio-separator` 作为替代。\n"
            "- **RVC**：默认使用 **rvc-python**（`RVCInference`）；填写 **RVC 命令模板** 时改为外部 CLI。需配置 `.pth`（及可选 `.index`），可调设备/音高算法/pitch 等。\n"
            "- **合成**：使用 pydub，请确保系统 PATH 中有 **ffmpeg**，或在配置中填写 ffmpeg 路径。\n\n"
            "**提示**：修改下方路径与命令后请先点击「保存翻唱流水线配置」，再执行流水线。"
        )
        _msc = config_manager.config.system_config
        with gr.Row():
            with gr.Column():
                mc_work_dir = gr.Textbox(
                    label="工作目录",
                    value=_msc.music_cover_work_dir or "./data/music_cover",
                )
                mc_yt_dlp = gr.Textbox(
                    label="yt-dlp 路径（可空=PATH）",
                    value=_msc.music_cover_yt_dlp_exe or "",
                )
                mc_ffmpeg = gr.Textbox(
                    label="ffmpeg 路径（可空=PATH）",
                    value=_msc.music_cover_ffmpeg_exe or "",
                )
                mc_uvr_tpl = gr.Textbox(
                    label="UVR/分离 命令模板",
                    placeholder='例: python C:/UVR/separate.py -i "{input_wav}" -o "{out_dir}"',
                    value=_msc.music_cover_uvr_cmd_template or "",
                    lines=2,
                )
                mc_rvc_tpl = gr.Textbox(
                    label="RVC 命令模板（非空则优先用 CLI，留空则用 rvc-python）",
                    placeholder='留空以使用 rvc-python；或例: python C:/RVC/infer_cli.py -i "{input_wav}" -o "{output_wav}" -mp "{model_pth}"',
                    value=_msc.music_cover_rvc_cmd_template or "",
                    lines=2,
                )
                mc_rvc_model = gr.Textbox(
                    label="RVC 模型 .pth",
                    value=_msc.music_cover_rvc_model_path or "",
                )
                mc_rvc_index = gr.Textbox(
                    label="RVC 索引 .index（可选）",
                    value=_msc.music_cover_rvc_index_path or "",
                )
                with gr.Accordion("rvc-python 推理参数", open=False):
                    mc_rvc_device = gr.Textbox(
                        label="device（如 cuda:0 / cpu）",
                        value=_msc.music_cover_rvc_device or "cuda:0",
                    )
                    mc_rvc_ver = gr.Dropdown(
                        choices=["v1", "v2"],
                        value=_msc.music_cover_rvc_model_version or "v2",
                        label="模型版本",
                    )
                    mc_rvc_f0 = gr.Dropdown(
                        choices=["rmvpe", "harvest", "crepe", "pm"],
                        value=_msc.music_cover_rvc_f0_method or "rmvpe",
                        label="音高提取 method",
                    )
                    mc_rvc_pitch = gr.Slider(
                        minimum=-12,
                        maximum=12,
                        value=float(_msc.music_cover_rvc_pitch),
                        step=0.5,
                        label="变调 pitch（半音）",
                    )
                    mc_rvc_ir = gr.Slider(
                        minimum=0.0,
                        maximum=1.0,
                        value=float(_msc.music_cover_rvc_index_rate),
                        step=0.05,
                        label="index_rate",
                    )
                    mc_rvc_fr = gr.Slider(
                        minimum=0,
                        maximum=7,
                        value=int(_msc.music_cover_rvc_filter_radius),
                        step=1,
                        label="filter_radius",
                    )
                    mc_rvc_rsr = gr.Number(
                        label="resample_sr（0=默认不重采样）",
                        value=int(_msc.music_cover_rvc_resample_sr),
                        precision=0,
                    )
                    mc_rvc_rmr = gr.Slider(
                        minimum=0.0,
                        maximum=1.0,
                        value=float(_msc.music_cover_rvc_rms_mix_rate),
                        step=0.05,
                        label="rms_mix_rate",
                    )
                    mc_rvc_pr = gr.Slider(
                        minimum=0.0,
                        maximum=0.5,
                        value=float(_msc.music_cover_rvc_protect),
                        step=0.01,
                        label="protect",
                    )
                mc_save_btn = gr.Button("保存翻唱流水线配置")
            with gr.Column():
                mc_src = gr.Radio(
                    choices=["YouTube", "Bilibili", "完整 URL"],
                    value="YouTube",
                    label="来源",
                )
                mc_query = gr.Textbox(
                    label="搜索词或 URL",
                    placeholder="YouTube/B站：歌名或歌手；URL：粘贴完整链接",
                    lines=2,
                )
                mc_pick = gr.Slider(
                    minimum=0,
                    maximum=7,
                    value=0,
                    step=1,
                    precision=0,
                    label="选用搜索结果中的第几条（从 0 开始）",
                )
                mc_skip_rvc = gr.Checkbox(label="跳过 RVC（仅用分离后人声合成）", value=False)
                mc_search_btn = gr.Button("预览搜索结果")
                mc_run_btn = gr.Button("执行完整流水线", variant="primary")
                mc_save_out = gr.Textbox(label="保存结果", interactive=False)
                mc_log = gr.Textbox(label="日志", lines=14, interactive=False)
                mc_audio = gr.Audio(label="成品试听（wav）", type="filepath", interactive=False)

        def _mc_source_key(label: str) -> str:
            return {"YouTube": "youtube", "Bilibili": "bilibili", "完整 URL": "url"}[label]

        mc_save_btn.click(
            config_manager.save_music_cover_config,
            inputs=[
                mc_work_dir,
                mc_yt_dlp,
                mc_ffmpeg,
                mc_uvr_tpl,
                mc_rvc_tpl,
                mc_rvc_model,
                mc_rvc_index,
                mc_rvc_device,
                mc_rvc_ver,
                mc_rvc_f0,
                mc_rvc_pitch,
                mc_rvc_ir,
                mc_rvc_fr,
                mc_rvc_rsr,
                mc_rvc_rmr,
                mc_rvc_pr,
            ],
            outputs=[mc_save_out],
        )

        mc_search_btn.click(
            lambda src, q: search_preview(config_manager.config.system_config, _mc_source_key(src), q),
            inputs=[mc_src, mc_query],
            outputs=[mc_log],
        )

        def _mc_run(src, q, pick, skip_rvc):
            try:
                r = run_pipeline(
                    config_manager.config.system_config,
                    source=_mc_source_key(src),
                    query=q,
                    pick_index=int(pick),
                    skip_rvc=bool(skip_rvc),
                )
                msg = format_pipeline_log(r)
                return msg, str(r.final_mix) if r.final_mix.exists() else None
            except Exception:
                return traceback.format_exc(), None

        mc_run_btn.click(_mc_run, inputs=[mc_src, mc_query, mc_pick, mc_skip_rvc], outputs=[mc_log, mc_audio])

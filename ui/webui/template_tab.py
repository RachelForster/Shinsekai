"""Chat template tab."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from ui.webui.chat_template_handlers import (
    generate_template,
    launch_chat,
    load_template_from_file,
    save_template,
    stop_chat,
)
from llm.template_generator import TRANSPARENT_BG
from ui.webui.context import WebUIContext


def register_template_tab(ctx: WebUIContext, character_name_list_len, background_name_list_len) -> None:

    with gr.Tab("聊天模板"):
        gr.Markdown("## 聊天模板管理")  
        gr.Markdown("您可以选择从文件导入模版或者选择人物生成模版")
        with gr.Row():
            with gr.Column():
                path_obj = Path(ctx.template_dir_path)
                template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
                selected_template = gr.Dropdown(
                    choices=template_files,
                    label="从文件导入"
                )

                load_template_btn = gr.Button("加载模板")

            with gr.Column():
                # 初始为空，通过事件更新
                selected_chars = gr.CheckboxGroup(
                    label="选择参与对话的角色",
                    choices=ctx.character_manager.get_character_name_list()
                )

                selected_bg = gr.Radio(
                    label="选择背景",
                    choices=ctx.background_manager.get_background_name_list() + [TRANSPARENT_BG],
                    value=TRANSPARENT_BG,
                    interactive=True,
                )

                use_effect = gr.Radio(label="是否开启特殊效果（人物离场、惊讶等效果）",choices=['是','否'], value="是")
                use_translation = gr.Radio(label="是否使用LLM翻译（比免费的API翻译得更精确）",choices=['是','否'],value="是")
                use_cg = gr.Radio(label="是否开启CG生成，得配置了ComfyUI才可以使用",choices=['是','否'],value="否")
                use_cot = gr.Radio(label="是否启用思维链（仅内部推理，不输出）",choices=['是','否'],value="否")

                generate_btn = gr.Button("生成模板")
        template_output = gr.Textbox(label="模板内容", lines=10, interactive=True)

        filename = gr.Textbox(label="保存的文件名", interactive=True)
        save_btn=gr.Button("保存模板")

        voice_mode = gr.Radio(
            choices=["全语音模式", "预设语音模式"],
            label="选择语音模式",
            value="预设语音模式",
            info="全语音模式中每句台词都生成语音，需要好的显卡、配置好GPT Sovits，预设语音模式只在立绘有语音时播放，对显卡无要求"
        )

        with gr.Row():
            initial_sprite_files = gr.Files(
                label="选择初始立绘图片（可选）",
            )
            history_file = gr.Textbox(
                label="输入历史记录文件路径（可选）",
                info="模版未变动时：上传文件将自动关联历史记录；留空则加载默认历史记录文件。模版变动时, 关联的历史文件也会变动。历史文件保存在./data/chat_history/目录下。",
            )
        with gr.Row():
            room_id = gr.Textbox(label="直播可选，输入bilibili房间ID", interactive=True, value=ctx.config_manager.config.system_config.live_room_id)
        launch_btn = gr.Button("启动聊天")
        launch_output = gr.Textbox(label="启动结果")
            
        stop_btn = gr.Button("关闭聊天")


        # 动态更新角色选择下拉框
        def update_template_dropdown():
            template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
            return gr.Dropdown(choices=template_files)
            
        # 当角色列表更新时，更新复选框选项
        def update_character_selection():
            return gr.CheckboxGroup(choices=ctx.character_manager.get_character_name_list())
        
        def update_bg_selection():
            return gr.Radio(
                choices=ctx.background_manager.get_background_name_list() + [TRANSPARENT_BG],
                value=TRANSPARENT_BG,
                interactive=True,
            )
            
        generate_btn.click(
            lambda sc, sb, ue, ut, ucg, ucot: generate_template(ctx, sc, sb, ue, ut, ucg, ucot),
            inputs=[selected_chars, selected_bg, use_effect, use_translation, use_cg, use_cot],
            outputs=[template_output, filename],
        )

        save_btn.click(
            lambda t, f: save_template(ctx, t, f),
            inputs=[template_output, filename],
            outputs=[launch_output, selected_template],
        ).then(
            update_template_dropdown,
            inputs=[],
            outputs=[selected_template],
        )

        launch_btn.click(
            lambda tpl, vm, init_sp, hist, sbg, ucg, rid: launch_chat(
                ctx, tpl, vm, init_sp, hist, sbg, ucg, rid
            ),
            inputs=[template_output, voice_mode, initial_sprite_files, history_file, selected_bg, use_cg, room_id],
            outputs=launch_output,
        )

        load_template_btn.click(
            lambda fp: load_template_from_file(ctx, fp),
            inputs=[selected_template],
            outputs=[template_output, filename],
        )

        stop_btn.click(
            stop_chat,
            inputs=[],
            outputs=[launch_output]
        )

        background_name_list_len.change(
            update_bg_selection,
            inputs=None,
            outputs=[selected_bg]
        )

        character_name_list_len.change(
            update_character_selection,
            inputs=None,
            outputs=[selected_chars]
        )

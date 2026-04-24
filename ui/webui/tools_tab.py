"""Utility tools tab."""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from tools.crop_sprite import batch_crop_upper_half
from tools.remove_bg import batch_remove_background
from ui.webui.context import WebUIContext


def register_tools_tab(ctx: WebUIContext, character_name_list_len) -> None:
    with gr.Tab("小工具"):
        gr.Markdown("# 立绘处理")
        gr.Markdown("## 批量自动生成立绘（需要提前配置好Gemini API Key）")
        with gr.Accordion(label="需要Gemini API Key和充值token, 建议大家还是去用免费的Gemini界面", open=False):
            with gr.Row():
                with gr.Column():
                        character_generate_sprites = gr.Dropdown(choices=ctx.character_manager.get_character_name_list())
                        sprite_num = gr.Slider(
                            minimum=1,      # 最小值
                            maximum=100,      # 最大值
                            value=1,      # 初始值
                            step=1,       # 步长/精度
                            label="生成立绘的数量", # 标签
                            interactive=True # 可交互
                        )
                        generate_sprite_prompts_button = gr.Button("生成立绘提示词")
                        ref_pic = gr.File(label="请输入参考图片")
                with gr.Column():
                    sprite_prompts = gr.TextArea(lines=10, label="立绘提示词，一行代表一个", interactive=True)
                    sprite_output_dir = gr.Textbox(label="请输入输出的目录，默认为data/sprite/角色上传目录名")
                    generate_sprites_btn=gr.Button("批量生成立绘")
                with gr.Column():    
                    sprites_generated_gallery = gr.Gallery(
                        label="已生成的立绘",
                        show_label=True,
                        elem_id="gallery",
                        columns=3,
                        object_fit="contain",
                        height="auto"
                    )
                    # regenerate_btn = gr.Button("重新生成该立绘")

                def generate_prompts(num, name):
                    prompt_list = ctx.image_generator.generate_prompts(num, ctx.config_manager.get_character_by_name(name).character_setting)
                    result = ''
                    index = 0
                    for item in prompt_list:
                        result = result + f'立绘 {index+1}：{item}\n'
                        index += 1
                    return result
                def generate_sprites(name,ref, prompt_list, dir):
                    prompt_list=prompt_list.strip().split('\n')
                    if not dir:
                        dir = Path('data/sprite') / ctx.config_manager.get_character_by_name(name).sprite_prefix
                    return ctx.image_generator.batch_generate_sprites(ref, prompt_list, dir)
                generate_sprite_prompts_button.click(
                    fn=generate_prompts,
                    inputs=[sprite_num, character_generate_sprites],
                    outputs=[sprite_prompts],
                )

                generate_sprites_btn.click(
                    generate_sprites,
                    inputs=[character_generate_sprites, ref_pic, sprite_prompts, sprite_output_dir],
                    outputs=[sprites_generated_gallery],
                )

                def update_tools_character_dropdown():
                    return gr.Dropdown(choices=ctx.character_manager.get_character_name_list())

                character_name_list_len.change(
                    update_tools_character_dropdown,
                    inputs=None,
                    outputs=[character_generate_sprites],
                )

        with gr.Row():
            with gr.Column():
                gr.Markdown("## 批量裁剪立绘")
                crop_input = gr.Textbox(label="请输入需要裁剪的目录")
                crop_output = gr.Textbox(label="输出目录，可以为空")
                crop_ratio = gr.Slider(
                    minimum=0,      # 最小值
                    maximum=1,      # 最大值
                    value=1,      # 初始值
                    step=0.05,       # 步长/精度
                    label="保留上半多少的比例，0.5是对半裁，0.8是保留上半80%的部分", # 标签
                    interactive=True # 可交互
                )
                crop_button=gr.Button("确认裁剪")
                    
            with gr.Column():
                gr.Markdown("## 批量抠出立绘")
                gr.Markdown(" ### 首次用的时候可能会先自动下载个模型，时间比较长")
                rmbg_input = gr.Textbox(label="请输入需要处理的目录")
                rmbg_output = gr.Textbox(label="输出目录，可以为空")
                rmbg_button=gr.Button("确认处理")
        with gr.Row():     
            crop_output_info = gr.Textbox(label="输出信息",interactive=False)

            crop_button.click(
                fn=batch_crop_upper_half,
                inputs=[crop_ratio, crop_input],
                outputs=[crop_output_info]
            )
            rmbg_button.click(
                fn=batch_remove_background,
                inputs=[rmbg_input, rmbg_output],
                outputs=[crop_output_info]
            )

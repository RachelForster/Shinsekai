"""Background management tab."""

from __future__ import annotations

import gradio as gr

from ui.webui.context import WebUIContext


def register_background_tab(ctx: WebUIContext, background_name_list_len, selected_bg_index) -> None:
    with gr.Tab("背景管理"):
        gr.Markdown("## 背景管理")
        with gr.Row():
            with gr.Column():
                gr.Markdown("#### 背景信息")
                selected_bg_group = gr.Dropdown(
                    choices=["新背景"] + ctx.background_manager.get_background_name_list(),
                    label="选择背景组"
                )
                export_bg_btn = gr.Button("导出到./output文件夹")
                del_bg_btn = gr.Button("删除背景组")
            with gr.Column():
                gr.Markdown("#### 从文件导入")
                import_bg_file = gr.File(label="选择文件")
                import_bg_btn = gr.Button("从文件导入背景组")
                import_bg_output = gr.Textbox("输出结果")

            # 导出背景
            export_bg_btn.click(
                ctx.background_manager.export_background_file,
                inputs=[selected_bg_group],
                outputs=[import_bg_output]
            )
            # 删除背景
            del_bg_btn.click(
                ctx.background_manager.delete_background,
                inputs=[selected_bg_group],
                outputs=[import_bg_output]
            ).then(
                lambda : gr.Dropdown(choices=['新背景']+ctx.background_manager.get_background_name_list()),
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda : "新背景",
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda : len(ctx.background_manager.get_background_name_list()),
                inputs=[],
                outputs=[background_name_list_len]
            )   

            # 导入背景
            import_bg_btn.click(
                ctx.background_manager.import_background_file,
                inputs=[import_bg_file],
                outputs=[import_bg_output]  
            ).then(
                lambda : gr.Dropdown(choices=['新背景']+ctx.background_manager.get_background_name_list()),
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda : "新背景",
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda : len(ctx.background_manager.get_background_name_list()),
                inputs=[],
                outputs=[background_name_list_len]
            )  
        with gr.Row():
            with gr.Column():
                bg_name = gr.Textbox(label="背景组名称", placeholder="请输入背景组名称")
                bg_prefix = gr.Textbox(label="上传数据目录名，请写英文，不要带汉语，例如：world1", value="temp")
                bg_save_btn = gr.Button("添加/保存背景组")
                bg_files = gr.Files(
                    label="上传背景图片",
                )
                upload_bg_btn = gr.Button("上传图片")
                upload_bg_output = gr.Textbox(label="上传结果")
                delete_all_bg_btn = gr.Button("删除所有背景图片")
                   
        with gr.Row():
            with gr.Column():
                # 显示已上传的背景图片
                def select_sprite(evt: gr.SelectData):
                    return evt.index
                    
                bg_gallery = gr.Gallery(
                    label="已上传的背景图片",
                    show_label=True,
                    elem_id="gallery",
                    columns=3,
                    object_fit="contain",
                    height="auto"
                )
                delete_single_bg_btn = gr.Button("删除选中背景图片")

            with gr.Column():
                gr.Markdown("### 描述背景")
                gr.Markdown(f"这些是{selected_bg_group.value}的背景图片，请你生成每张背景图片的地点，氛围，格式为：背景 1：xxx")
                bg_info_inputs = gr.Textbox(label="背景描述：", lines=20)
                upload_bg_info_btn=gr.Button("上传背景信息")

        with gr.Row():
            with gr.Column():
                gr.Markdown("#### 背景信息")
                bgm_files = gr.Files(
                    label="上传背景音乐",
                )
                upload_bgm_btn = gr.Button("上传音乐")
                upload_bgm_output = gr.Textbox(label="上传结果")
                delete_all_bgm_btn = gr.Button("删除所有背景音乐")
        with gr.Row():
            with gr.Column():
                # 显示已上传的背景音乐
                def select_sprite(evt: gr.SelectData):
                    return evt.index
                    
                bgm_list_display = gr.Dataframe(
                    headers=["选择", "序号", "文件名", "路径", "标签描述"],
                    datatype=["bool", "number", "str", "str", "str"],
                    wrap=True,
                    interactive=True, 
                    label="背景音乐列表 (勾选要删除的项，点击行播放)"
                )

                # --- 实时播放音频组件 ---
                audio_player = gr.Audio(
                    label="选中行音频播放器", 
                    interactive=True, 
                    type="filepath"
                )

                delete_selected_bgms_btn = gr.Button("批量删除选中的音乐条")    
                bgm_output_message = gr.Textbox(label="操作结果", interactive=False)
                
            with gr.Column():
                gr.Markdown("### 描述背景音乐")
                gr.Markdown(f"这些是{selected_bg_group.value}的背景音乐，请你生成每条背景音乐的情绪，氛围，格式为：音乐 1：xxx")
                bgm_info_inputs = gr.Textbox(label="背景音乐描述：", lines=20)
                upload_bgm_info_btn=gr.Button("上传背景音乐描述")
                    
                # 上传音乐
                upload_bgm_btn.click(
                    fn=ctx.background_manager.upload_bgms,
                    inputs=[selected_bg_group, bgm_files],
                    outputs=[upload_bgm_output, bgm_list_display, bgm_info_inputs]
                )
                # 1. 绑定行点击事件 (实现实时播放)
                bgm_list_display.select(
                    fn=ctx.background_manager.handle_bgm_selection,
                    inputs=[bgm_list_display],
                    outputs=[bgm_output_message, audio_player],
                    show_progress=True,
                )

                # 2. 绑定背景选择事件 (用于加载列表)
                # (此处的 load_bgms_and_tags 需要更新，以便它返回 Audio 的 update)
                # 假设 load_bgms_and_tags 函数返回 (dataframe, tags_text)
                selected_bg_group.change(
                    fn=ctx.background_manager.load_bgms_and_tags,
                    inputs=[selected_bg_group],
                    outputs=[bgm_list_display, bgm_info_inputs], 
                    show_progress=False
                )
                    
                delete_selected_bgms_btn.click(
                    fn=ctx.background_manager.batch_delete_bgms,
                    inputs=[selected_bg_group, bgm_list_display, bgm_info_inputs],
                    outputs=[bgm_output_message, bgm_list_display, bgm_info_inputs]
                )

                upload_bgm_info_btn.click(
                    fn=ctx.background_manager.upload_bgm_tags,
                    inputs=[selected_bg_group,bgm_info_inputs],
                    outputs=[bgm_output_message]
                )
                
            bg_gallery.select(
                fn=select_sprite,
                inputs=None,
                outputs=[selected_bg_index]
            )

            # 修改或添加背景组
            bg_save_btn.click(
                ctx.background_manager.add_background,
                inputs=[bg_name, bg_prefix],
                outputs=[upload_bg_output, selected_bg_group]
            ).then(
                lambda : gr.Dropdown(choices=['新背景']+ctx.background_manager.get_background_name_list()),
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda x: x,
                inputs=bg_name,
                outputs=selected_bg_group
            ).then(
                lambda : len(ctx.background_manager.get_background_name_list()),
                inputs=[],
                outputs=[background_name_list_len]
            )

            upload_bg_info_btn.click(
                ctx.background_manager.upload_bg_tags,
                inputs=[selected_bg_group, bg_info_inputs],
                outputs=[upload_bg_output]
            )
                
            # 当选择背景组时更新立绘显示
            selected_bg_group.change(
                ctx.background_manager.get_background_sprites,
                inputs=[selected_bg_group],
                outputs=[bg_gallery, bg_info_inputs, bg_files]
            )

            def get_bg_info(name):
                bg = ctx.config_manager.get_background_by_name(name)
                if bg is None:
                    return '',''
                return bg.name, bg.sprite_prefix

            selected_bg_group.change(
                get_bg_info,
                inputs=[selected_bg_group],
                outputs=[bg_name, bg_prefix]
            )

            delete_all_bg_btn.click(
                ctx.background_manager.delete_all_sprites,
                inputs=[selected_bg_group],
                outputs=[upload_bg_output, bg_gallery, bg_info_inputs]
            )

            delete_single_bg_btn.click(
                ctx.background_manager.delete_single_sprite,
                inputs=[selected_bg_group, selected_bg_index],
                outputs=[upload_bg_output, bg_gallery, bg_info_inputs]
            )

            upload_bg_btn.click(
                ctx.background_manager.upload_sprites,
                inputs=[selected_bg_group, bg_files, bg_info_inputs],
                outputs=[upload_bg_output, bg_gallery, bg_info_inputs]
            )

            upload_bg_info_btn.click(
                ctx.background_manager.upload_bg_tags,
                inputs=[selected_bg_group, bg_info_inputs],
                outputs=[upload_bg_output]
            )

"""Character settings tab."""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr

import tools.file_util as fu
from config.character_config import CharacterConfig
from ui.webui.context import WebUIContext


def register_character_tab(ctx: WebUIContext, character_name_list_len, selected_sprite_index) -> None:
    with gr.Tab("人物设定"):
        gr.Markdown("## 人物管理")
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 人物管理")
                gr.Markdown("#### 加载或添加可用角色")
                selected_character = gr.Dropdown(
                    choices=["新角色"] + ctx.character_manager.get_character_name_list(),
                    label="选择角色"
                )
                export_btn = gr.Button("导出到./output文件夹")
                del_btn = gr.Button("删除人物")
                def update_character_dropdown():
                    return gr.Dropdown(choices=["新角色"]+ctx.character_manager.get_character_name_list())
                    
                def update_character_information(selected_character):
                    character = ctx.config_manager.get_character_by_name(selected_character)
                    if character == None:
                        return "","","","","","","","",""
                    return character.name, character.color, character.sprite_prefix, character.gpt_model_path, character.sovits_model_path, character.refer_audio_path, character.prompt_text, character.prompt_lang, character.character_setting
                    
            with gr.Column():
                gr.Markdown("#### 从文件导入")
                import_file = gr.File(label="选择文件", file_count="multiple")
                import_btn = gr.Button("从文件导入人物")
                import_output = gr.Textbox("输出结果")

                def export_character(character_name):
                    character = ctx.config_manager.get_character_by_name(character_name)
                    if character is None:
                        return "人物不存在"
                    try:
                        output_path = Path('./output')
                        output_path.mkdir(parents=True,exist_ok=True)
                        character = CharacterConfig.parse_dic(char_data=character.__dict__)
                        fu.export_character([character], output_path=f'./output/{character.name}.char')
                        return "导出成功"
                    except Exception as e:
                        return f"导出失败 {e}"
                        
                def import_character(file_paths):
                    if not file_paths:
                        return "请先选择文件"
                    
                    success_count = 0
                    error_messages = []
                        
                    # file_paths is a list
                    for file_path in file_paths:
                        try:
                            fu.import_character(file_path)
                            success_count += 1
                        except Exception as e:
                            error_messages.append(f"文件 {os.path.basename(file_path)} 导入失败: {e}")
                
                    ctx.config_manager.reload()
                        
                    result_msg = f"成功导入 {success_count} 个角色。"
                    if error_messages:
                        result_msg += "\n失败详情：\n" + "\n".join(error_messages)
                            
                    return result_msg

        with gr.Row():
            with gr.Column():
                gr.Markdown("#### 角色信息")
                char_name = gr.Textbox(label="人物名称", placeholder="请输入人物名称")
                char_color = gr.ColorPicker(label="名称显示颜色", value="#d07d7d")
                sprite_prefix = gr.Textbox(label="上传数据目录名，请写英文，不要带汉语，例如：komaeda", value="temp")
            with gr.Column():
                gr.Markdown("#### 角色设定")
                character_setting = gr.TextArea(label="角色设定，写出角色的背景信息，性格特点，语言习惯", interactive=True)
                ai_help_btn = gr.Button("AI 一键帮写")
            
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 语音模块设置")
                gr.Markdown("#### 以下如果没有可以为空，如果你想让角色读出台词，就需要填写")
                gpt_model_path = gr.Textbox(label="GPT 模型路径，如果没有可以为空")
                sovits_model_path = gr.Textbox(label="SoVITS 模型路径")
                refer_audio_path = gr.Textbox(label="参考音频路径")
                prompt_text = gr.Textbox(label="参考音频的文字内容")
                prompt_lang = gr.Textbox(label="参考音频的语言, 英语填en，日语填ja，中文填zh")
                add_btn = gr.Button("添加或保存人物设置")
                add_output = gr.Textbox(label="操作结果")

        # 添加人物事件
        add_btn.click(
            ctx.character_manager.add_character,
            inputs=[
                char_name, char_color, sprite_prefix, gpt_model_path,
                sovits_model_path, refer_audio_path, prompt_text, prompt_lang, character_setting
            ],
            outputs=[
                add_output
            ]
        ).then(
            update_character_dropdown,
            inputs=None,
            outputs=selected_character
        ).then(
            lambda x: x,
            inputs=char_name,
            outputs=selected_character
        ).then(
            lambda : len(ctx.character_manager.get_character_name_list()),
            inputs=[],
            outputs=[character_name_list_len]
        )
        # 删除人物事件
        del_btn.click(
            ctx.character_manager.delete_character,
            inputs=[selected_character],
            outputs=[add_output]
        ).then(
            update_character_dropdown,
            inputs=None,
            outputs=selected_character
        ).then(
            lambda: ("","","","","","","","",""),
            inputs=None,
            outputs=[char_name, char_color, sprite_prefix, gpt_model_path,
                      sovits_model_path, refer_audio_path, prompt_text, prompt_lang, character_setting]
        ).then(
            lambda : len(ctx.character_manager.get_character_name_list()),
            inputs=[],
            outputs=[character_name_list_len]
        )

        selected_character.change(
            update_character_information,
            inputs=[selected_character],
            outputs=[
                char_name, char_color, sprite_prefix, gpt_model_path,
                sovits_model_path, refer_audio_path, prompt_text, prompt_lang, character_setting
            ]
        )

        export_btn.click(
            export_character,
            inputs=[selected_character],
            outputs=[import_output]
        )

        import_btn.click(
            import_character,
            inputs=[import_file],
            outputs=[import_output]
        ).then(
            update_character_dropdown,
            inputs=[],
            outputs=[selected_character]
        ).then(
            lambda : len(ctx.character_manager.get_character_name_list()),
            inputs=[],
            outputs=[character_name_list_len]
        )

        ai_help_btn.click(
            ctx.character_manager.generate_character_setting,
            inputs=[char_name, character_setting],
            outputs=[import_output, character_setting]
        )
            
        # 立绘上传和情绪标注区域
        gr.Markdown("## 立绘管理")
        with gr.Row():
            with gr.Column():
                copy_drop_down = selected_character

                sprite_files = gr.Files(
                    label="上传立绘图片",
                )
                upload_sprites_btn = gr.Button("上传图片")
                upload_output = gr.Textbox(label="上传结果")

                # 添加滑块控件
                sprite_scale = gr.Slider(
                    minimum=0,      # 最小值
                    maximum=3,      # 最大值
                    value=1.0,      # 初始值
                    step=0.05,       # 步长/精度
                    label="选择立绘放大/缩小倍数，如果发现立绘过大、过小可以来调节", # 标签
                    interactive=True # 可交互
                )
                sprite_scale_save_btn = gr.Button("保存立绘放大/缩小倍数")
                delete_all_sprites_btn = gr.Button("删除所有立绘")
                   
        with gr.Row():
            with gr.Column():
                # 显示已上传的立绘
                sprites_gallery = gr.Gallery(
                    label="已上传的立绘",
                    show_label=True,
                    elem_id="gallery",
                    columns=3,
                    object_fit="contain",
                    height="auto"
                )
                delete_single_sprite_btn = gr.Button("删除选中立绘")

            with gr.Column():
                # 动态生成情绪标签输入框
                gr.Markdown("### 标注立绘情绪关键字")
                gr.Markdown(f"这些是{selected_character.value}的立绘，请你生成每张立绘的情绪、动作关键字，格式为：立绘 1：xxx")
                emotion_inputs = gr.Textbox(label="情绪关键字描述：", lines=20)
                upload_emotion_btn=gr.Button("上传立绘标注")
                

            # 上传立绘事件
            upload_sprites_btn.click(
                ctx.character_manager.upload_sprites,
                inputs=[selected_character, sprite_files, emotion_inputs],
                outputs=[upload_output, sprites_gallery, emotion_inputs]
            )

            upload_emotion_btn.click(
                ctx.character_manager.upload_emotion_tags,
                inputs=[selected_character, emotion_inputs],
                outputs=[upload_output]
            )

            def get_sprite_scale(name):    
                character=ctx.config_manager.get_character_by_name(name)
                if character:
                    return character.sprite_scale
                else:
                    return 1.0
                
            # 当选择角色时更新立绘显示
            selected_character.change(
                ctx.character_manager.get_character_sprites,
                inputs=[selected_character],
                outputs=[sprites_gallery, emotion_inputs, sprite_files]
            )

            #上传scale
            sprite_scale_save_btn.click(
                ctx.character_manager.save_sprite_scale,
                inputs=[selected_character, sprite_scale],
                outputs=[upload_output]
            )

            selected_character.change(
                get_sprite_scale,
                inputs=[selected_character],
                outputs=[sprite_scale]
            )

            delete_all_sprites_btn.click(
                ctx.character_manager.delete_all_sprites,
                inputs=[selected_character],
                outputs=[upload_output, sprites_gallery, emotion_inputs]
            )

            delete_single_sprite_btn.click(
                ctx.character_manager.delete_single_sprite,
                inputs=[selected_character, selected_sprite_index],
                outputs=[upload_output, sprites_gallery, emotion_inputs]
            )

            with gr.Column(scale=1):
                gr.Markdown("### 选择立绘并上传语音（可选）")
                gr.Markdown("""
                - 如果没有配置GPT-SOVITS，这里上传的音频就会绑定立绘直接播放
                - 如果配置了GPT-SOVITS，如果某个立绘需要和默认参考音频不同的感情，可上传不同的参考音频，并填写其语音文本内容
                """)
                # 当点击立绘时，更新选中的立绘索引
                def select_sprite(evt: gr.SelectData):
                    return evt.index
                    
                sprites_gallery.select(
                    fn=select_sprite,
                    inputs=None,
                    outputs=selected_sprite_index
                )
                    
                # 显示当前选中的立绘信息
                selected_sprite_info = gr.Textbox(label="当前选中的立绘", interactive=False)
                    
                # 语音播放组件
                sprite_voice_player = gr.Audio(label="立绘语音（可在 API 设定中选择是否使用 TTS 引擎合成）", interactive=False)
                    
                # 语音上传组件
                voice_upload = gr.Audio(
                    label="上传语音文件",
                    sources=["upload"],
                    type="filepath"
                )
                sprite_voice_text = gr.Textbox(label="立绘语音内容，如果该语音是参考语音需填写", interactive=True)
                    
                upload_voice_btn = gr.Button("上传语音")
                voice_upload_output = gr.Textbox(label="上传结果")
                    
                # 更新选中立绘信息
                def update_selected_sprite_info(character_name, sprite_index):
                    if not character_name or sprite_index is None:
                        return "未选择立绘", None, ""
                        
                    character = ctx.config_manager.get_character_by_name(character_name)
                    if not character or not character.sprites or sprite_index >= len(character.sprites):
                        return "立绘不存在", None,""
                        
                    sprite = character.sprites[sprite_index]
                    if isinstance(sprite,dict):
                        voice_path = sprite.get("voice_path")
                        voice_text = sprite.get("voice_text")
                    else:
                        voice_path = sprite.voice_path
                        voice_text = sprite.voice_text
                        
                    info = f"立绘 {sprite_index+1}"
                    if voice_path:
                        info += " (已有语音)"
                    else:
                        info += " (无语音)"
                        
                    return info, voice_path if voice_path else None, voice_text
                    
                # 当选择立绘或切换角色时更新信息
                selected_sprite_index.change(
                    fn=update_selected_sprite_info,
                    inputs=[selected_character, selected_sprite_index],
                    outputs=[selected_sprite_info, sprite_voice_player, sprite_voice_text]
                )
                    
                selected_character.change(
                    fn=lambda char_name: update_selected_sprite_info(char_name, selected_sprite_index.value) if selected_sprite_index.value is not None else ("未选择立绘", None),
                    inputs=[selected_character],
                    outputs=[selected_sprite_info, sprite_voice_player]
                )
                    
                # 上传语音事件
                upload_voice_btn.click(
                    fn=ctx.character_manager.upload_voice,
                    inputs=[selected_character, selected_sprite_index, voice_upload, sprite_voice_text],
                    outputs=[voice_upload_output, sprite_voice_player]
                ).then(
                    fn=update_selected_sprite_info,
                    inputs=[selected_character, selected_sprite_index],
                    outputs=[selected_sprite_info, sprite_voice_player, sprite_voice_text]
                )                

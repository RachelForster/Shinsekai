import gradio as gr
import yaml
import os
import shutil
from pathlib import Path
import json
import subprocess
import hashlib
import glob
import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
import tools.file_util as fu
from config.character_config import CharacterConfig
from config.character_manager import CharacterManager
from config.config_manager import ConfigManager
from config.background_manager import BackgroundManager
from llm.constants import LLM_BASE_URLS

config_manager = ConfigManager()
character_manager = CharacterManager()
background_manager = BackgroundManager()
main_process = None

# 创建存储上传文件的目录
TEMPLATE_DIR_PATH = "./data/character_templates"
HISTORY_DIR='./data/chat_history'

#Template Page
def load_template_from_file(file_path):
    try:
        file_name = file_path
        file_path = os.path.join(TEMPLATE_DIR_PATH, file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            template = f.read()
        return template, file_name
    except Exception as e:
        return f"加载失败: {str(e)}", file_name
def generate_template(selected_characters, bg_name):
    if not selected_characters:
        return "请至少选择一个角色！", ""
    
    names = ""

    # 让同样的人物生成同样的模板，就会有一样的md5了，进而会有同样的聊天历史文件。
    selected_characters = sorted(selected_characters)

    for char_name in selected_characters:
        names += f"{char_name},"

    template = f"你需要模拟一个RPG剧情对话系统，出场人物有：{names}\n"

    template += '''
每次输出时，必须严格使用 JSON 格式，结构为：
{
  "dialog": [
    {
      "character_name": "角色名",
      "sprite": "对应的立绘ID",
      "speech": "该角色说的中文台词",
      "translate": "该角色说的话的日文翻译（可选）"
    }
  ]
}
    '''
    template += "\n立绘说明:\n"
    for char_name in selected_characters:
        char_detail = config_manager.get_character_by_name(char_name)
        template += f"{char_name}有{len(char_detail.sprites)}张立绘：\n"
        template += f"{char_detail.emotion_tags}\n\n"

    template += "\n角色说明：\n"
    for char_name in selected_characters:
        char_detail = config_manager.get_character_by_name(char_name)
        if char_detail.character_setting:
            template += f"以下是{char_name}的角色设定：\n"
            character_setting = char_detail.character_setting
            template += f"{character_setting}\n\n"

    if bg_name:
        bg = config_manager.get_background_by_name(bg_name)
        if bg and bg.sprites:
            template +="场景说明：\n"
            template += f"现在有{len(bg.sprites)}个可用场景：\n"
            template += f"{bg.bg_tags}\n\n"

        if bg and bg.bgm_list:
            template += "BGM说明：\n"
            template += f"现在有{len(bg.bgm_list)}个可用BGM：\n"
            template += f"{bg.bgm_tags}\n\n"

    template +=f"""
要求：
1. 不要输出除 JSON 以外的任何文本。
2. character_name 只能是{names} 或者旁白,选项,数值,场景,bgm。
3. sprite 字段必须填写一个立绘数字代号，只允许是两位数字（例如 01, 02，你需根据台词语气自动选择合适的立绘。当角色名为旁白，数值或选项时，该字段为-1。当角色名为场景时，可以从场景中选择场景编号，代表切换场景, 如果要切换场景，它必须出现在第一个元素。当角色名为bgm时，sprite的值代表bgm编号，可以根据不同的氛围切换bgm, 不要太频繁。
4. speech 字段是角色的台词，必须符合角色的性格和说话风格。
5. 所有对话都必须放在 "dialog" 数组中，数组内按对话顺序排列。数组中有至少两个元素。
6. 旁白描写是场景动作描写
7. 你必须在dialog最后一个元素中添加选项，选项元素的character_name必须是选项，内容在speech内，选项如果多于两个请用"/"分隔，xx选项必须是用户可以选择的对话、行为等，选项中不能出现任何多余的描述和内容，必须是纯文本。选项里有一个是纯粹插科打诨，无厘头的，有一个是非常精明的选项，另一个中庸的选项，选项必须符合角色的性格和说话风格，选项必须和当前的剧情相关联，不能无关紧要。
8. 数值可以用富文本，可以添加颜色、emoji等表示，颜色尽量浅一些，符合马卡龙配色，例如 <span style='color:xxxx;'>HP：100</span>，选项元素的character_name必须是数值，内容在speech内，如果有多个数值，请用<br>分隔开，在这里，数值代表角色的状态或者用户的状态。
"""
    template += "\n请开始对话，开始时介绍下用户所处的情境和背景，设定初始的场景和bgm,以及在做什么事情：\n"
    return template, ""
def launch_chat(template, voice_mode, init_sprite_path, history_file, selected_bg):
    global main_process
    print("启动聊天，使用模板:")
    try:
        dest_path = os.path.join(TEMPLATE_DIR_PATH,'_temp.txt')
        with open(dest_path, mode='+wt',encoding="utf-8") as file:
            file.write(template)

        voice_mode = 'gen' if voice_mode == '全语音模式' else 'preset'
        init_path = init_sprite_path[0] if init_sprite_path else ''
        history_file = history_file if history_file else ''

        if main_process is None or main_process.poll() is not None:
            # 计算模板内容的哈希值（使用 SHA256 算法）
            template_hash = hashlib.md5(template.encode('utf-8')).hexdigest()
            history_file_path = Path(history_file) if history_file else Path(f"{HISTORY_DIR}/{template_hash}.json")
            python_path = 'python'
            runtime_python_path = Path('./runtime')
            if runtime_python_path.exists():
                python_path = './runtime/python.exe'
            main_process = subprocess.Popen(
                [python_path, 
                 'main_sprite.py', 
                 '--template=_temp', 
                 f'--voice_mode={voice_mode}',
                 f'--init_sprite_path={init_path}',
                 f'--history={history_file_path.resolve()}',
                 f'--bg={selected_bg}'
                 ]
            )
            return "聊天进程已启动！PID: " + str(main_process.pid)
        else:
            return "进程已经在运行中！PID: " + str(main_process.pid)
    except Exception as e:
        print("启动模版失败：", e)
def stop_chat():
    global main_process
    if main_process is not None and main_process.poll() is None:
        main_process.terminate()  # 发送终止信号
        main_process.wait()       # 等待进程结束
        pid = main_process.pid
        main_process = None
        return f"进程 {pid} 已停止！"
    else:
        return "没有正在运行的进程！"
def save_template(template, filename):
    path_obj = Path(TEMPLATE_DIR_PATH)
    template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
    if filename == "":
        return "保存文件名不能为空！", template_files
    try:
        dest_path=""
        if filename.endswith(".txt"):
            dest_path = os.path.join(TEMPLATE_DIR_PATH,f'{filename}')
        else:
            dest_path = os.path.join(TEMPLATE_DIR_PATH,f'{filename}.txt')
        with open(dest_path, mode='+wt',encoding="utf-8") as file:
            file.write(template)
        path_obj = Path(TEMPLATE_DIR_PATH)
        template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
        return "保存成功", template_files
    except Exception as e:
        return f"保存失败，{e}",template_files


# 创建界面
with gr.Blocks(title="新世界程序") as demo:
    gr.Markdown("# 新世界程序")
    gr.Markdown('''
    - （b站、小红书）作者：不二咲爱笑 
    - github: https://github.com/RachelForster/Shinsekai qq交流群：1033281516、本软件是开源软件，禁止商用
    ''')
    with gr.Tab("API 设定"):
        gr.Markdown("## API 配置")
        with gr.Row():
            with gr.Column():
                _provider,_model,_base_url,_api_key = config_manager.get_llm_api_config()
                gr.Markdown("### LLM API 配置")
                llm_provider = gr.Dropdown(
                    choices=list(LLM_BASE_URLS.keys()),
                    label="选择大语言模型供应商",
                    value=_provider
                )
                llm_provider_value = config_manager.config.api_config.llm_provider
                llm_model = gr.Textbox(label="模型ID", value=_model)
                api_key = gr.Textbox(label="LLM API Key", type="password", value=_api_key)
                base_url = gr.Textbox(label="LLM API 基础网址", value=_base_url)
            with gr.Column():
                    api_output = gr.Textbox(label="输出信息", interactive=False)
        with gr.Row():
            with gr.Column():
                _gsv_url,_gpt_sovits_work_path = config_manager.get_gpt_sovits_config()
                gr.Markdown("### GPT SoVITS API 配置，如果没有可以不填，如果你想让角色读出台词，就需要配置")
                gr.Markdown("#### 前提条件")
                gr.Markdown('''
                1. 你的GPU大于等于6G
                2. 下载好GPT-SOVITS整合包
                ''')
                sovits_url = gr.Textbox(label="GPT-SoVITS API 调用地址", value=_gsv_url)
                gpt_sovits_api_path = gr.Textbox(label="GPT-SoVITS 服务启动路径", value=_gpt_sovits_work_path)
                save_api_btn = gr.Button("保存配置")
            with gr.Column():
                gr.Markdown("### 下载GPT SOVITS整合包")
                gr.HTML('''
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
                ''')
                with gr.Accordion("使用说明", open=False):
                    gr.Markdown("""
                    如果你想让角色读出台词，则需要下载GPT-SOVITS整合包。
                    ### 解压和使用步骤:
                    1. 下载完成后，使用7-Zip或类似工具解压文件
                    2. 将解压后的文件夹目录填写在GPT-SOVITS 服务启动路径中，注意该目录下有api_v2.py
                    
                    ### 注意事项:
                    - 确保有足够的磁盘空间(至少11GB可用空间)
                    - 建议使用稳定的网络环境下载
                    - 如遇下载问题，请检查网络连接或稍后重试
                    """)
            
        
        # Add events to update the dropdowns and base URL
        llm_provider.change(
            config_manager.update_llm_info,
            inputs=llm_provider,
            outputs=[base_url,llm_model,api_key]
        )

        save_api_btn.click(
            config_manager.save_api_config_new,
            inputs=[llm_provider, llm_model,api_key, base_url, sovits_url, gpt_sovits_api_path],
            outputs=api_output
        )

    active_character=gr.State("") #当前选中的人物名
    selected_sprite_index = gr.State(None)  # 存储当前选中的立绘索引
    selected_bg_index = gr.State(None)
    init_sprite_path = gr.State("")
    history_file_path = gr.State("")

    with gr.Tab("人物设定"):
        gr.Markdown("## 人物管理")
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 人物管理")
                gr.Markdown("#### 加载或添加可用角色")
                selected_character = gr.Dropdown(
                    choices=["新角色"] + character_manager.get_character_name_list(),
                    label="选择角色"
                )
                export_btn = gr.Button("导出到./output文件夹")
                del_btn = gr.Button("删除人物")
                def update_character_dropdown():
                    return gr.Dropdown(choices=["新角色"]+character_manager.get_character_name_list())
                
                def update_character_information(selected_character):
                    character = config_manager.get_character_by_name(selected_character)
                    if character == None:
                        return "","","","","","","","",""
                    return character.name, character.color, character.sprite_prefix, character.gpt_model_path, character.sovits_model_path, character.refer_audio_path, character.prompt_text, character.prompt_lang, character.character_setting
                
            with gr.Column():
                gr.Markdown("#### 从文件导入")
                import_file = gr.File(label="选择文件")
                import_btn = gr.Button("从文件导入人物")
                import_output = gr.Textbox("输出结果")

                def export_character(character_name):
                    character = config_manager.get_character_by_name(character_name)
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
                    
                def import_character(file_path):
                    try:
                        fu.import_character(file_path)
                        config_manager.reload()
                        return f"导入成功"
                    except Exception as e:
                        return f"导入失败：{e}"

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
            character_manager.add_character,
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
        )
        # 删除人物事件
        del_btn.click(
            character_manager.delete_character,
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
        )

        ai_help_btn.click(
            character_manager.generate_character_setting,
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
                character_manager.upload_sprites,
                inputs=[selected_character, sprite_files, emotion_inputs],
                outputs=[upload_output, sprites_gallery, emotion_inputs]
            )

            upload_emotion_btn.click(
                character_manager.upload_emotion_tags,
                inputs=[selected_character, emotion_inputs],
                outputs=[upload_output]
            )

            def get_sprite_scale(name):    
                character=config_manager.get_character_by_name(name)
                if character:
                    return character.sprite_scale
                else:
                    return 1.0
            
            # 当选择角色时更新立绘显示
            selected_character.change(
                character_manager.get_character_sprites,
                inputs=[selected_character],
                outputs=[sprites_gallery, emotion_inputs, sprite_files]
            )

            #上传scale
            sprite_scale_save_btn.click(
                character_manager.save_sprite_scale,
                inputs=[selected_character, sprite_scale],
                outputs=[upload_output]
            )

            selected_character.change(
                get_sprite_scale,
                inputs=[selected_character],
                outputs=[sprite_scale]
            )

            delete_all_sprites_btn.click(
                character_manager.delete_all_sprites,
                inputs=[selected_character],
                outputs=[upload_output, sprites_gallery, emotion_inputs]
            )

            delete_single_sprite_btn.click(
                character_manager.delete_single_sprite,
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
                sprite_voice_player = gr.Audio(label="立绘语音，预设语音模式直接播放，但全语音模式就可以作为参考音频", interactive=False)
                
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
                    
                    character = config_manager.get_character_by_name(character_name)
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
                    fn=character_manager.upload_voice,
                    inputs=[selected_character, selected_sprite_index, voice_upload, sprite_voice_text],
                    outputs=[voice_upload_output, sprite_voice_player]
                ).then(
                    fn=update_selected_sprite_info,
                    inputs=[selected_character, selected_sprite_index],
                    outputs=[selected_sprite_info, sprite_voice_player, sprite_voice_text]
                )                
    with gr.Tab("背景管理"):
        gr.Markdown("## 背景管理")
        with gr.Row():
            with gr.Column():
                gr.Markdown("#### 背景信息")
                selected_bg_group = gr.Dropdown(
                    choices=["新背景"] + background_manager.get_background_name_list(),
                    label="选择背景组"
                )
                export_bg_btn = gr.Button("导出到./output文件夹")
                del_bg_btn = gr.Button("删除背景组")
            with gr.Column():
                gr.Markdown("#### 从文件导入")
                import_bg_file = gr.File(label="选择文件")
                import_bg_btn = gr.Button("从文件导入背景组")
                import_bg_output = gr.Textbox("输出结果")

            def update_character_dropdown():
                    return gr.Dropdown(choices=["新角色"]+character_manager.get_character_name_list())

            export_bg_btn.click(
                background_manager.export_background_file,
                inputs=[selected_bg_group],
                outputs=[import_bg_output]
            )
            del_bg_btn.click(
                background_manager.delete_background,
                inputs=[selected_bg_group],
                outputs=[import_bg_output]
            ).then(
                lambda : gr.Dropdown(choices=['新背景']+background_manager.get_background_name_list()),
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda : "新背景",
                inputs=None,
                outputs=selected_bg_group
            )

            import_bg_btn.click(
                background_manager.import_background_file,
                inputs=[import_bg_file],
                outputs=[import_bg_output]  
            ).then(
                lambda : gr.Dropdown(choices=['新背景']+background_manager.get_background_name_list()),
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda : "新背景",
                inputs=None,
                outputs=selected_bg_group
            )
        with gr.Row():
            with gr.Column():
                bg_name = gr.Textbox(label="背景组名称", placeholder="请输入背景组名称")
                bg_prefix = gr.Textbox(label="上传数据目录名，请写英文，不要带汉语，例如：world1", value="temp")
                bg_save_btn = gr. Button("添加/保存背景组")
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
                    fn=background_manager.upload_bgms,
                    inputs=[selected_bg_group, bgm_files],
                    outputs=[upload_bgm_output, bgm_list_display, bgm_info_inputs]
                )
                # 1. 绑定行点击事件 (实现实时播放)
                bgm_list_display.select(
                    fn=background_manager.handle_bgm_selection,
                    inputs=[bgm_list_display],
                    outputs=[bgm_output_message, audio_player],
                    show_progress=True,
                )

                # 2. 绑定背景选择事件 (用于加载列表)
                # (此处的 load_bgms_and_tags 需要更新，以便它返回 Audio 的 update)
                # 假设 load_bgms_and_tags 函数返回 (dataframe, tags_text)
                selected_bg_group.change(
                    fn=background_manager.load_bgms_and_tags,
                    inputs=[selected_bg_group],
                    outputs=[bgm_list_display, bgm_info_inputs], 
                    show_progress=False
                )
                
                delete_selected_bgms_btn.click(
                    fn=background_manager.batch_delete_bgms,
                    inputs=[selected_bg_group, bgm_list_display, bgm_info_inputs],
                    outputs=[bgm_output_message, bgm_list_display, bgm_info_inputs]
                )

                upload_bgm_info_btn.click(
                    fn=background_manager.upload_bgm_tags,
                    inputs=[selected_bg_group,bgm_info_inputs],
                    outputs=[bgm_output_message]
                )
            
            bg_gallery.select(
                fn=select_sprite,
                inputs=None,
                outputs=[selected_bg_index]
            )

            bg_save_btn.click(
                background_manager.add_background,
                inputs=[bg_name, bg_prefix],
                outputs=[upload_bg_output, selected_bg_group]
            ).then(
                lambda : gr.Dropdown(choices=['新背景']+background_manager.get_background_name_list()),
                inputs=None,
                outputs=selected_bg_group
            ).then(
                lambda x: x,
                inputs=bg_name,
                outputs=selected_bg_group
            )

            upload_bg_info_btn.click(
                background_manager.upload_bg_tags,
                inputs=[selected_bg_group, bg_info_inputs],
                outputs=[upload_bg_output]
            )
            
            # 当选择背景组时更新立绘显示
            selected_bg_group.change(
                background_manager.get_background_sprites,
                inputs=[selected_bg_group],
                outputs=[bg_gallery, bg_info_inputs, bg_files]
            )

            def get_bg_info(name):
                bg = config_manager.get_background_by_name(name)
                if bg is None:
                    return '',''
                return bg.name, bg.sprite_prefix

            selected_bg_group.change(
                get_bg_info,
                inputs=[selected_bg_group],
                outputs=[bg_name, bg_prefix]
            )

            delete_all_bg_btn.click(
                background_manager.delete_all_sprites,
                inputs=[selected_bg_group],
                outputs=[upload_bg_output, bg_gallery, bg_info_inputs]
            )

            delete_single_bg_btn.click(
                background_manager.delete_single_sprite,
                inputs=[selected_bg_group, selected_bg_index],
                outputs=[upload_bg_output, bg_gallery, bg_info_inputs]
            )

            upload_bg_btn.click(
                background_manager.upload_sprites,
                inputs=[selected_bg_group, bg_files, bg_info_inputs],
                outputs=[upload_bg_output, bg_gallery, bg_info_inputs]
            )

            upload_bg_info_btn.click(
                background_manager.upload_bg_tags,
                inputs=[selected_bg_group, bg_info_inputs],
                outputs=[upload_bg_output]
            )

    with gr.Tab("聊天模板"):
        gr.Markdown("## 聊天模板管理")  
        gr.Markdown("您可以选择从文件导入模版或者选择人物生成模版")
        with gr.Row():
            with gr.Column():
                path_obj = Path(TEMPLATE_DIR_PATH)
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
                    choices=character_manager.get_character_name_list()
                )

                selected_bg = gr.Radio(
                    label="选择背景",
                    choices=background_manager.get_background_name_list()+['透明背景'],
                    interactive=True
                )
                
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
        launch_btn = gr.Button("启动聊天")
        launch_output = gr.Textbox(label="启动结果")
        
        stop_btn = gr.Button("关闭聊天")


        # 动态更新角色选择下拉框
        def update_template_dropdown():
            template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
            return gr.Dropdown(choices=template_files)
        
        # 当角色列表更新时，更新复选框选项
        def update_character_selection():
            return gr.CheckboxGroup(choices=character_manager.get_character_name_list())
    
        def update_bg_selection():
            return gr.Radio(choices=background_manager.get_background_name_list() + ['透明背景'], interactive=True)
        
        generate_btn.click(
            generate_template,
            inputs=[selected_chars, selected_bg],
            outputs=[template_output, filename]
        )

        save_btn.click(
            save_template,
            inputs=[template_output, filename],
            outputs=[launch_output,selected_template]
        ).then(
            update_template_dropdown,
            inputs=[],
            outputs=[selected_template]
        )

        launch_btn.click(
            launch_chat,
            inputs=[template_output, voice_mode, initial_sprite_files, history_file, selected_bg],
            outputs=launch_output
        )

        load_template_btn.click(
            load_template_from_file,
            inputs=[selected_template],
            outputs=[template_output, filename]
        )

        stop_btn.click(
            stop_chat,
            inputs=[],
            outputs=[launch_output]
        )
        
        selected_character.change(
            update_character_selection,
            inputs=None,
            outputs=[selected_chars]
        )

        selected_bg_group.change(
            update_bg_selection,
            inputs=None,
            outputs=[selected_bg]
        )

if __name__ == "__main__":
    demo.launch()
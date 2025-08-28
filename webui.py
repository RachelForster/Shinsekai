import gradio as gr
import yaml
import os
import shutil
from pathlib import Path
import json
import subprocess

# 存储数据的全局变量
api_config = {
    "llm_api_key": "",
    "llm_base_url": "",
    "gpt_sovits_url": ""
}

characters = []

main_process = None

# 创建存储上传文件的目录
UPLOAD_DIR = "./data/sprite"
API_CONFIG_PATH = "./data/config/api.yaml"
CHARACTER_CONFIG_PATH = "./data/config/characters.yaml"
TEMPLATE_DIR_PATH = "./data/character_templates"
Path(UPLOAD_DIR).mkdir(exist_ok=True)

def save_api_config(api_key, base_url, sovits_url, gpt_sovits_api_path):
    global api_config
    api_config = {
        "llm_api_key": api_key,
        "llm_base_url": base_url,
        "gpt_sovits_url": sovits_url,
        "gpt_sovits_api_path": gpt_sovits_api_path
    }
    yaml.dump(api_config, open(API_CONFIG_PATH, 'w', encoding='utf-8'), allow_unicode=True)
    return "API配置已保存！"

def load_api_config_from_file():
    global api_config
    try:
        with open(API_CONFIG_PATH, 'r', encoding='utf-8') as f:
            api_config = yaml.safe_load(f) or {}
        return "API配置已加载！"
    except Exception as e:
        return f"加载失败: {str(e)}"

def load_characters_from_file():
    global characters
    try:
        with open(CHARACTER_CONFIG_PATH, 'r', encoding='utf-8') as f:
            loaded_characters = yaml.safe_load(f) or []
            characters.clear()
            characters.extend(loaded_characters)
        return "人物设定已加载！", [[c.get("name", ""), c.get("color", ""), c.get("prompt_lang", "")] for c in characters]
    except Exception as e:
        return f"加载失败: {str(e)}", [[c.get("name", ""), c.get("color", ""), c.get("prompt_lang", "")] for c in characters]

def save_characters_to_file():
    global characters
    try:
        # 保存到当前目录下的characters.yaml文件
        file_path = CHARACTER_CONFIG_PATH
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(characters, f, allow_unicode=True)
        return f"人物设定已保存到 {file_path}！"
    except Exception as e:
        return f"保存失败: {str(e)}"

def add_character(name, color, sprite_prefix, gpt_model_path, 
                 sovits_model_path, refer_audio_path, prompt_text, prompt_lang):
    global characters
    
    if not name:
        return "名称不能为空！", [c.get("name", "") for c in characters]
        
    character = next((c for c in characters if c["name"] == name), None)
    if character is None:
        character = {
            "name": name,
            "color": color,
            "sprite_prefix": sprite_prefix,
            "gpt_model_path": gpt_model_path,
            "sovits_model_path": sovits_model_path,
            "refer_audio_path": refer_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "sprites": [],  # 新增：存储立绘和情绪标签
            "emotion_tags": ""
        }    
        characters.append(character)
        save_characters_to_file()
        return "人物已添加！", [c.get("name", "") for c in characters]
    else:
        character["name"]=name
        character["color"]=color
        character["sprite_prefix"]=sprite_prefix
        character["gpt_model_path"]=gpt_model_path
        character["sovits_model_path"]=sovits_model_path
        character["prompt_text"]=prompt_text
        character["prompt_lang"]=prompt_lang
        character["ref_audio_path"]=refer_audio_path
        save_characters_to_file()
        return "人物已更新！", [c.get("name", "") for c in characters]

def load_template_from_file(file_path):
    try:
        file_name = file_path
        file_path = os.path.join(TEMPLATE_DIR_PATH, file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            template = f.read()
        return template, file_name
    except Exception as e:
        return f"加载失败: {str(e)}", file_name

def generate_template(selected_characters):
    if not selected_characters:
        return "请至少选择一个角色！", ""
    
    names = ""
    for char_name in selected_characters:
        char_detail = next((c for c in characters if c['name'] == char_name), None)
        if char_detail:
            names += f"{char_name},"
    
    template = f"你需要模拟弹丸论破中{names}的对话:\n"
    template += '''
每次输出时，必须严格使用 JSON 格式，结构为：
{
  "dialog": [
    {
      "character_name": "角色名",
      "sprite": "对应的立绘ID",
      "speech": "该角色说的话"
    }
  ]
}
    '''
    template += "\n立绘说明:\n"
    for char_name in selected_characters:
        char_detail = next((c for c in characters if c['name'] == char_name), None)
        template += f"{char_name}有{len(char_detail['sprites'])}张立绘：\n"
        template += f"{char_detail['emotion_tags']}\n\n"

    template +=f"""
要求：
1. 不要输出除 JSON 以外的任何文本。
2. character_name 只能是{names} 或者旁白。
3. sprite 字段必须填写一个立绘数字代号，只允许是两位数字（例如 01, 02，你需根据台词语气自动选择合适的立绘。当角色名为旁白时，该字段为-1。
4. speech 字段是角色的台词，必须符合角色的性格和说话风格。
5. 所有对话都必须放在 "dialog" 数组中，数组内按对话顺序排列。数组中有至少两个元素。
6. 旁白描写是场景动作描写\n
"""
    template += "\n请开始对话:\n"
    return template, ""

def update_character_options():
    return gr.CheckboxGroup(choices=[c.get("name", "") for c in characters])

def upload_sprites(character_name, sprite_files, emotion_tags):
    """上传立绘并为每张图标注情绪关键词"""
    if not character_name:
        return "请先选择或创建角色！", []
    
    if not sprite_files:
        return "请选择要上传的图片！", []
    
    # 找到对应的角色
    character = next((c for c in characters if c["name"] == character_name), None)
    if not character:
        return f"找不到角色: {character_name}", []
    
    # 创建角色专属目录
    char_dir = os.path.join(UPLOAD_DIR, character["sprite_prefix"])
    Path(char_dir).mkdir(parents=True, exist_ok=True)
    
    # 处理上传的图片
    if character["sprites"] is None:
        character["sprites"]=[]
    uploaded_sprites = []
    for i, file in enumerate(sprite_files):
        # 获取文件名和扩展名
        filename = os.path.basename(file.name)
        # 保存文件到角色目录
        dest_path = os.path.join(char_dir, filename)
        shutil.copyfile(file.name, dest_path)
        
        # 添加到角色的立绘列表
        character["sprites"].append({
            "path": dest_path,
        })
        uploaded_sprites.append((dest_path))
    
    character["emotion_tags"]=emotion_tags

    # 保存到文件
    save_characters_to_file()
    
    return f"成功为 {character_name} 上传 {len(sprite_files)} 张立绘！", uploaded_sprites

def upload_emotion_tags(character_name, emotion_tags):
    if not character_name:
        return "请先选择或创建角色！"
    
    if not emotion_inputs:
        return "请输入情绪标注！"
    
    # 找到对应的角色
    character = next((c for c in characters if c["name"] == character_name), None)
    if not character:
        return f"找不到角色: {character_name}"
    try:
        character["emotion_tags"]=emotion_tags
        return "标注成功！"
    except Exception as e:
        return f"标注出错了：{e}"

# TODO 写一下启动聊天的逻辑
def launch_chat(template):
    global main_process
    print("启动聊天，使用模板:")
    try:
        dest_path = os.path.join(TEMPLATE_DIR_PATH,'_temp.txt')
        with open(dest_path, mode='+wt',encoding="utf-8") as file:
            file.write(template)

        if main_process is None or main_process.poll() is not None:
            # 启动一个长时间运行的进程（这里使用ping作为示例）
            main_process = subprocess.Popen(
                ['./runtime/python.exe', 'main_sprite.py',  '--template=_temp']
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



def get_character_sprites(character_name):
    """获取指定角色的所有立绘"""
    if not character_name:
        return [],"",[]
    
    character = next((c for c in characters if c["name"] == character_name), None)
    if (not character) or ("sprites" not in character):
        return [],"",[]
    elif "emotion_tags" not in character:
        return [(s["path"]) for s in character["sprites"]], "",[]
    
    return [(s["path"]) for s in character["sprites"]], character["emotion_tags"],[]

# 创建界面
with gr.Blocks(title="LLM 角色管理") as demo:
    load_characters_from_file()
    load_api_config_from_file()
    gr.Markdown("# LLM 角色管理系统")
    
    with gr.Tab("API 设定"):
        gr.Markdown("## API 配置")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### LLM API 配置")
                api_key = gr.Textbox(label="LLM API Key", type="password", value=api_config.get("llm_api_key", ""))
                base_url = gr.Textbox(label="LLM API 基础网址", value=api_config.get("llm_base_url", ""))
                gr.Markdown("### GPT SoVITS API 配置，如果没有可以不填")
                sovits_url = gr.Textbox(label="GPT-SoVITS API 调用地址", value=api_config.get("gpt_sovits_url", ""))
                gpt_sovits_api_path = gr.Textbox(label="GPT-SoVITS 服务启动路径", value=api_config.get("gpt_sovits_api_path", ""))
                save_api_btn = gr.Button("保存配置")
            with gr.Column():
                api_output = gr.Textbox(label="输出信息", interactive=False)
        
        save_api_btn.click(
            save_api_config,
            inputs=[api_key, base_url, sovits_url, gpt_sovits_api_path],
            outputs=api_output
        )
    
    active_character=gr.State("")

    with gr.Tab("人物设定"):
        gr.Markdown("## 人物管理")
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 人物管理")
                gr.Markdown("#### 加载或添加可用角色")
                selected_character = gr.Dropdown(
                    choices=["新角色"] + [c.get("name", "") for c in characters],
                    label="选择角色"
                )
                def update_character_dropdown():
                    return gr.Dropdown(choices=["新角色"]+[c.get("name", "") for c in characters])
                
                def update_character_information(selected_character):
                    character = next((c for c in characters if c["name"] == selected_character), None)
                    if character == None:
                        return "","","","","","","",""
                    return character["name"], character["color"], character["sprite_prefix"], character["gpt_model_path"], character["sovits_model_path"], character["refer_audio_path"], character["prompt_text"], character["prompt_lang"]
                                
                gr.Markdown("#### 角色信息")
                char_name = gr.Textbox(label="人物名称", placeholder="请输入人物名称")
                char_color = gr.ColorPicker(label="名称颜色", value="#EC955F")
                sprite_prefix = gr.Textbox(label="立绘上传目录名，请写英文，不要带汉语，例如：komaeda", value="komaeda")
                gr.Markdown("### 语音模块设置")
                gr.Markdown("#### 以下如果没有可以为空")
                gpt_model_path = gr.Textbox(label="GPT 模型路径")
                sovits_model_path = gr.Textbox(label="SoVITS 模型路径， 如果没有可为空")
                refer_audio_path = gr.Textbox(label="参考音频路径，如果没有可为空")
                prompt_text = gr.Textbox(label="参考音频文本")
                prompt_lang = gr.Textbox(label="参考音频的语言", value="ja")
                add_btn = gr.Button("添加或保存人物设置")
                add_output = gr.Textbox(label="操作结果")
    

        # 添加人物事件
        add_btn.click(
            add_character,
            inputs=[
                char_name, char_color, sprite_prefix, gpt_model_path,
                sovits_model_path, refer_audio_path, prompt_text, prompt_lang
            ],
            outputs=[
                add_output
            ]
        ).then(
            update_character_dropdown,
            inputs=None,
            outputs=selected_character
        ).then(
            lambda : char_name,
            inputs=None,
            outputs=selected_character
        )
        
        selected_character.change(
            update_character_information,
            inputs=[selected_character],
            outputs=[
                char_name, char_color, sprite_prefix, gpt_model_path,
                sovits_model_path, refer_audio_path, prompt_text, prompt_lang
            ]
        )
        
        # 新增：立绘上传和情绪标注区域
        gr.Markdown("## 立绘管理")
        with gr.Row():
            with gr.Column():
                copy_drop_down = selected_character

                sprite_files = gr.Files(
                    label="上传立绘图片",
                )

                # 显示已上传的立绘
                sprites_gallery = gr.Gallery(
                    label="已上传的立绘",
                    show_label=True,
                    elem_id="gallery",
                    columns=3,
                    object_fit="contain",
                    height="auto"
                )
                upload_sprites_btn = gr.Button("上传图片")
                upload_output = gr.Textbox(label="上传结果")

                # 动态生成情绪标签输入框
                gr.Markdown(f"这些是xxx的立绘，请你生成每张立绘的情绪关键字，格式为：立绘01：xxx")
                emotion_inputs = gr.Textbox(label="情绪关键字描述：", lines=20)
                
                upload_emotion_btn=gr.Button("上传立绘标注")
                
            # 上传立绘事件
            upload_sprites_btn.click(
                upload_sprites,
                inputs=[selected_character, sprite_files, emotion_inputs],
                outputs=[upload_output, sprites_gallery]
            )

            upload_emotion_btn.click(
                upload_emotion_tags,
                inputs=[selected_character, emotion_inputs],
                outputs=[upload_output]
            )
            
            # 当选择角色时更新立绘显示
            selected_character.change(
                get_character_sprites,
                inputs=[selected_character],
                outputs=[sprites_gallery, emotion_inputs, sprite_files]
            )
    
    with gr.Tab("聊天模板"):
        gr.Markdown("## 聊天模板管理")  
        path_obj = Path(TEMPLATE_DIR_PATH)
        template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
        selected_template = gr.Dropdown(
            choices=template_files,
            label="从文件导入"
        )

        load_template_btn = gr.Button("加载模板")
        
        # 动态更新角色选择下拉框
        def update_template_dropdown():
            template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
            return gr.Dropdown(choices=template_files)

        # 初始为空，通过事件更新
        selected_chars = gr.CheckboxGroup(
            label="选择参与对话的角色",
            choices=[c.get("name", "") for c in characters]
        )
        
        generate_btn = gr.Button("生成模板")
        template_output = gr.Textbox(label="模板内容", lines=10, interactive=True)

        filename = gr.Textbox(label="保存的文件名", interactive=True)
        save_btn=gr.Button("保存模板")

        launch_btn = gr.Button("启动聊天")
        launch_output = gr.Textbox(label="启动结果")
        
        stop_btn = gr.Button("关闭聊天")

        # 当角色列表更新时，更新复选框选项
        def update_character_selection():
            return gr.CheckboxGroup(choices=[c.get("name", "") for c in characters])
        
        generate_btn.click(
            generate_template,
            inputs=[selected_chars],
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
            inputs=[template_output],
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

if __name__ == "__main__":
    demo.launch()
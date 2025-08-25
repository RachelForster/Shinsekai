import gradio as gr
import yaml
import os
import shutil
from pathlib import Path
import json

# 存储数据的全局变量
api_config = {
    "llm_api_key": "",
    "llm_base_url": "",
    "gpt_sovits_url": ""
}

characters = []

# 创建存储上传文件的目录
UPLOAD_DIR = "./data/uploads"
API_CONFIG_PATH = "./data/config/api.yaml"
CHARACTER_CONFIG_PATH = "./data/config/characters.yaml"
Path(UPLOAD_DIR).mkdir(exist_ok=True)

def save_api_config(api_key, base_url, sovits_url):
    global api_config
    api_config = {
        "llm_api_key": api_key,
        "llm_base_url": base_url,
        "gpt_sovits_url": sovits_url
    }
    yaml.dump(api_config, open(API_CONFIG_PATH, 'w', encoding='utf-8'), allow_unicode=True)
    return "API配置已保存！"

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
        return "名称不能为空！", [[c.get("name", ""), c.get("color", ""), c.get("prompt_lang", "")] for c in characters], "", "", "", "", "", "", ""
    
    new_character = {
        "name": name,
        "color": color,
        "sprite_prefix": sprite_prefix,
        "gpt_model_path": gpt_model_path,
        "sovits_model_path": sovits_model_path,
        "refer_audio_path": refer_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "sprites": []  # 新增：存储立绘和情绪标签
    }
    
    characters.append(new_character)
    return "人物已添加！", [[c.get("name", ""), c.get("color", ""), c.get("prompt_lang", "")] for c in characters], "", "", "", "", "", "", ""


def generate_template(selected_characters):
    if not selected_characters:
        return "请至少选择一个角色！"
    
    template = f"对话模板 - 参与角色: {', '.join(selected_characters)}\n\n"
    template += "系统: 你是一个助手，需要与以下角色进行对话:\n"
    
    for char_name in selected_characters:
        char_detail = next((c for c in characters if c['name'] == char_name), None)
        if char_detail:
            template += f"- {char_name} (颜色: {char_detail['color']}, 语言: {char_detail['prompt_lang']})\n"
    
    template += "\n请开始对话:\n"
    return template

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
    char_dir = os.path.join(UPLOAD_DIR, character_name, "sprites")
    Path(char_dir).mkdir(parents=True, exist_ok=True)
    
    # 处理上传的图片
    uploaded_sprites = []
    for i, file in enumerate(sprite_files):
        # 获取文件名和扩展名
        filename = os.path.basename(file.name)
        # 保存文件到角色目录
        dest_path = os.path.join(char_dir, filename)
        shutil.copyfile(file.name, dest_path)
        
        # 获取对应的情绪标签
        emotion = emotion_tags[i] if i < len(emotion_tags) else "未标注"
        
        # 添加到角色的立绘列表
        character["sprites"].append({
            "path": dest_path,
            "emotion": emotion
        })
        
        uploaded_sprites.append((dest_path, emotion))
    
    return f"成功为 {character_name} 上传 {len(sprite_files)} 张立绘！", uploaded_sprites

# TODO 写一下启动聊天的逻辑
def launch_chat(template):
    print("启动聊天，使用模板:")

def get_character_sprites(character_name):
    """获取指定角色的所有立绘"""
    if not character_name:
        return []
    
    character = next((c for c in characters if c["name"] == character_name), None)
    if not character or "sprites" not in character:
        return []
    
    return [(s["path"], s["emotion"]) for s in character["sprites"]]

# 创建界面
with gr.Blocks(title="LLM 角色管理") as demo:
    load_characters_from_file()
    gr.Markdown("# LLM 角色管理系统")
    
    with gr.Tab("API 设定"):
        gr.Markdown("## API 配置")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### LLM API 配置")
                api_key = gr.Textbox(label="LLM API Key", type="password")
                base_url = gr.Textbox(label="LLM API 基础网址", value="https://api.openai.com/v1")
                gr.Markdown("### SoVITS API 配置，如果没有可以不填")
                sovits_url = gr.Textbox(label="GPT-SoVITS API 地址")
                save_api_btn = gr.Button("保存配置")
            with gr.Column():
                api_output = gr.Textbox(label="输出信息", interactive=False)
        
        save_api_btn.click(
            save_api_config,
            inputs=[api_key, base_url, sovits_url],
            outputs=api_output
        )
    
    with gr.Tab("人物设定"):
        gr.Markdown("## 人物管理")
        
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 人物管理")
                char_name = gr.Textbox(label="人物名称", placeholder="请输入人物名称")
                char_color = gr.ColorPicker(label="名称颜色", value="#EC955F")
                sprite_prefix = gr.Textbox(label="立绘前缀", value="./data/sprite/")
                
                gr.Markdown("### 语音模块设置")
                gr.Markdown("#### 以下如果没有可以为空")
                gpt_model_path = gr.Textbox(label="GPT 模型路径")
                sovits_model_path = gr.Textbox(label="SoVITS 模型路径， 如果没有可为空")
                refer_audio_path = gr.Textbox(label="参考音频路径，如果没有可为空")
                prompt_text = gr.Textbox(label="参考音频文本")
                prompt_lang = gr.Textbox(label="参考音频的语言", value="ja")
                
                add_btn = gr.Button("添加人物")
                add_output = gr.Textbox(label="操作结果")
            

            with gr.Column(scale=1):
                gr.Markdown("### 可用人物列表")
                for character in characters:
                    gr.Markdown(f"- {character.get('name', '')}")

        # 添加人物事件
        add_btn.click(
            add_character,
            inputs=[
                char_name, char_color, sprite_prefix, gpt_model_path,
                sovits_model_path, refer_audio_path, prompt_text, prompt_lang
            ],
            outputs=[
                add_output, char_name, char_color, sprite_prefix,
                gpt_model_path, sovits_model_path, refer_audio_path, prompt_text, prompt_lang
            ]
        )
        
        # 新增：立绘上传和情绪标注区域
        gr.Markdown("## 立绘管理")
        with gr.Row():
            with gr.Column():
                selected_character = gr.Dropdown(
                    choices=[c.get("name", "") for c in characters],
                    label="选择角色"
                )
                
                # 动态更新角色选择下拉框
                def update_character_dropdown():
                    return gr.Dropdown(choices=[c.get("name", "") for c in characters])
                
                
                sprite_files = gr.Files(
                    label="上传立绘图片",
                    file_types=["image"]
                )
                
                # 动态生成情绪标签输入框
                emotion_inputs = []
                with gr.Column():
                    for i in range(5):  # 预设5个输入框，可以根据需要调整
                        emotion_inputs.append(gr.Textbox(
                            label=f"立绘 #{i+1} 情绪关键词",
                            placeholder="例如: 高兴,生气,悲伤"
                        ))
                
                upload_sprites_btn = gr.Button("上传并标注立绘")
                upload_output = gr.Textbox(label="上传结果")
                
                # 显示已上传的立绘
                sprites_gallery = gr.Gallery(
                    label="已上传的立绘",
                    show_label=True,
                    elem_id="gallery",
                    columns=3,
                    object_fit="contain",
                    height="auto"
                )
            
            # 上传立绘事件
            upload_sprites_btn.click(
                upload_sprites,
                inputs=[selected_character, sprite_files] + emotion_inputs,
                outputs=[upload_output, sprites_gallery]
            )
            
            # 当选择角色时更新立绘显示
            selected_character.change(
                get_character_sprites,
                inputs=[selected_character],
                outputs=[sprites_gallery]
            )
    
    with gr.Tab("聊天模板"):
        gr.Markdown("## 聊天模板生成")
        
        # 初始为空，通过事件更新
        selected_chars = gr.CheckboxGroup(
            label="选择参与对话的角色",
            choices=[c.get("name", "") for c in characters]
        )
        
        generate_btn = gr.Button("生成模板")
        template_output = gr.Textbox(label="生成的模板", lines=10, interactive=True)

        launch_btn = gr.Button("启动聊天")
        launch_output = gr.Textbox(label="启动结果")

        # 当角色列表更新时，更新复选框选项
        def update_character_selection():
            return gr.CheckboxGroup(choices=[c.get("name", "") for c in characters])
        
        generate_btn.click(
            generate_template,
            inputs=[selected_chars],
            outputs=template_output
        )

        launch_btn.click(
            launch_chat,
            inputs=[template_output],
            outputs=launch_output
        )

if __name__ == "__main__":
    load_characters_from_file()
    print("人物设定已加载！", characters)
    demo.launch()
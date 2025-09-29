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
from llm.constants import LLM_BASE_URLS, LLM_MODELS
from llm.llm_manager import LLMAdapterFactory, LLMManager

# 存储数据的全局变量
api_config = {
    "llm_api_key": {},
    "llm_base_url": "",
    "llm_provider": "Deepseek",
    "llm_model": {},
    "gpt_sovits_url": "",
    "gpt_sovits_api_path":""
}

llm_manager = None

characters = []

main_process = None

# 创建存储上传文件的目录
UPLOAD_DIR = "./data/sprite"
VOICE_DIR = "./data/speech"
MODEL_DIR = "./data/models"
API_CONFIG_PATH = "./data/config/api.yaml"
CHARACTER_CONFIG_PATH = "./data/config/characters.yaml"
TEMPLATE_DIR_PATH = "./data/character_templates"
Path(UPLOAD_DIR).mkdir(exist_ok=True)

def generate_character_setting(name, setting):
    global characters
    global llm_manager
    global api_config

    if not name:
        return "请选择或输入要生成的角色的名字！", setting
    
    character = next((c for c in characters if c["name"] == name), None)
    if character is None:
        add_character(name=name, color='', sprite_prefix='', gpt_model_path='', 
                sovits_model_path='', refer_audio_path='', prompt_text='', prompt_lang='', character_setting=setting)
        character = next((c for c in characters if c["name"] == name), None)
    
    setting = "无" if not setting else setting

    template = f"""
    你需要帮助用户写出{name}的角色设定，包括{name}的背景信息，性格特点，和语言习惯。输出plain text格式，不要使用markdown格式。
    将{name}的背景信息，性格特点，和语言习惯分段写，并且同一段内标号，不一定是3点，有可能比3点多。
    输出格式示例：
    {name}的背景信息：
    1.姓名和出处：
    2.外表：
    3.背景：
    4.经历：

    {name}的性格特点：
    1.
    2.
    3.

    {name}的语言习惯：
    1.
    2.
    """
    try:
        if llm_manager is None:
            llm_provider = api_config.get("llm_provider","Deepseek")
            llm_model = api_config.get("llm_model").get(llm_provider,'')
            api_key =api_config.get("llm_api_key").get(llm_provider,'')
            if not llm_provider:
                print("Please choose the llm provider")
                return "请先设定大语言模型供应商", setting
            llm_adapter = LLMAdapterFactory.create_adapter(llm_provider=llm_provider, api_key=api_key,base_url=api_config.get("llm_base_url",""), model = llm_model)
            llm_manager = LLMManager(adapter=llm_adapter,user_template = template)
        llm_manager.set_user_template(template)
        character["character_setting"] = llm_manager.chat(f"补充信息：{setting},请输出结果：", stream = False, response_format={"type":"text"})
        return "输出成功", character['character_setting']
    except Exception as e:
        return f"输出失败:{e}", setting

def save_api_config(llm_provider, llm_model, api_key, base_url, sovits_url, gpt_sovits_api_path):
    global api_config
    llm_api_key = api_config.get("llm_api_key",{})
    llm_model_map = api_config.get("llm_model",{})
    llm_api_key = {} if llm_api_key is None else llm_api_key
    llm_api_key[llm_provider] = api_key
    llm_model_map[llm_provider] = llm_model
    api_config = {
        "llm_api_key": llm_api_key,
        "llm_base_url": base_url,
        "llm_provider": llm_provider,
        "llm_model": llm_model_map,
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
                 sovits_model_path, refer_audio_path, prompt_text, prompt_lang, character_setting):
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
            "sprites": [],
            "sprite_scale": 1.0,
            "emotion_tags": "",
            "character_setting": "",
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
        character["refer_audio_path"]=refer_audio_path
        character["character_setting"]=character_setting
        save_characters_to_file()
        return "人物已更新！", [c.get("name", "") for c in characters]
def delete_character(name):
    global characters
    if not name or name == "新角色":
        return "请选择要删除的角色！", [c.get("name", "") for c in characters]
    
    character = next((c for c in characters if c["name"] == name), None)
    if character is None:
        return f"找不到角色: {name}", [c.get("name", "") for c in characters]
    
    characters.remove(character)
    save_characters_to_file()

    sprite_prefix = character.get("sprite_prefix", '')
    if not sprite_prefix
        return "已删除角色", [c.get("name", "") for c in characters]
     
    # 删除角色的立绘目录
    char_dir = os.path.join(UPLOAD_DIR, character["sprite_prefix"])
    if os.path.exists(char_dir):
        shutil.rmtree(char_dir)
    
    # 删除角色的语音目录
    voice_char_dir = os.path.join(VOICE_DIR, character["sprite_prefix"])
    if os.path.exists(voice_char_dir):
        shutil.rmtree(voice_char_dir)

    # 删除角色的gpt-sovits相关模型和语音
    model_char_dir = os.path.join(MODEL_DIR, character["sprite_prefix"])
    if os.path.exists(model_char_dir):
        shutil.rmtree(model_char_dir)
    
    return f"角色 {name} 已删除！", [c.get("name", "") for c in characters]

def load_template_from_file(file_path):
    try:
        file_name = file_path
        file_path = os.path.join(TEMPLATE_DIR_PATH, file_path)
        with open(file_path, 'r', encoding='utf-8') as f:
            template = f.read()
        return template, file_name
    except Exception as e:
        return f"加载失败: {str(e)}", file_name
def save_sprite_scale(name, scale):
    global characters
    
    if not name:
        return "名称不能为空！", [c.get("name", "") for c in characters]
    character = next((c for c in characters if c["name"] == name), None)

    if character:
        character['sprite_scale'] = scale
        save_characters_to_file()
        return "保存立绘缩放倍率成功"

def generate_template(selected_characters):
    if not selected_characters:
        return "请至少选择一个角色！", ""
    
    names = ""

    # 让同样的人物生成同样的模板，就会有一样的md5了，进而会有同样的聊天历史文件。
    selected_characters = sorted(selected_characters)

    for char_name in selected_characters:
        names += f"{char_name},"
    
    template = f"你需要模拟{names}的对话:\n"

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

    template += "\n角色说明：\n"
    for char_name in selected_characters:
        char_detail = next((c for c in characters if c['name'] == char_name), None)
        if char_detail.get("character_setting",''):
            template += f"以下是{char_name}的角色设定：\n"
            template += f"{char_detail.get("character_setting","")}\n\n"
        
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
        return "请先选择或创建角色！", [], ''
    
    if not sprite_files:
        return "请选择要上传的图片！", [], ''
    
    # 找到对应的角色
    character = next((c for c in characters if c["name"] == character_name), None)
    if not character:
        return f"找不到角色: {character_name}", [], ''
    
    # 创建角色专属目录
    char_dir = os.path.join(UPLOAD_DIR, character["sprite_prefix"])
    Path(char_dir).mkdir(parents=True, exist_ok=True)

    files = glob.glob(os.path.join(char_dir, '*'))
    
    for file in files:
        try:
            if os.path.isfile(file):
                os.remove(file)  # 删除文件
                print(f"已删除文件: {file}")
        except Exception as e:
            print(f"删除文件 {file} 时出错: {e}")
            return '失败', [], ''

    
    # 处理上传的图片
    emotion_tags=''
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
        emotion_tags +=f'立绘 {i+1}：\n'
    
    character["emotion_tags"]=emotion_tags

    # 保存到文件
    save_characters_to_file()
    
    return f"成功为 {character_name} 上传 {len(sprite_files)} 张立绘！", uploaded_sprites, emotion_tags

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
        save_characters_to_file()
        return "标注成功！"
    except Exception as e:
        return f"标注出错了：{e}"

def upload_voice(character_name, sprite_index, voice_file, voice_text):
    """为指定立绘上传语音文件"""
    if not character_name:
        return "请先选择角色！", None
    
    # 找到对应的角色
    character = next((c for c in characters if c["name"] == character_name), None)
    if not character:
        return f"找不到角色: {character_name}", None
    
    # 确保有立绘
    if not character["sprites"] or sprite_index >= len(character["sprites"]):
        return "立绘不存在！", None
    
    original_voice_path = character["sprites"][sprite_index].get("voice_path","")
    if (not voice_file) and (not original_voice_path):
        return "请选择语音文件！", None
    
    # 创建语音目录
    voice_char_dir = os.path.join(VOICE_DIR, character["sprite_prefix"])
    Path(voice_char_dir).mkdir(parents=True, exist_ok=True)
    
    # 保存语音文件
    voice_filename = f"voice_{sprite_index:02d}{voice_file[voice_file.rfind('.'): ]}"
    voice_path = os.path.join(voice_char_dir, voice_filename)
    shutil.copyfile(voice_file, voice_path)
    
    # 更新角色数据
    character["sprites"][sprite_index]["voice_path"] = voice_path
    character["sprites"][sprite_index]["voice_text"] = voice_text
    save_characters_to_file()
    
    return f"语音已上传到立绘 {sprite_index+1}！", voice_path

def get_sprite_voice(character_name, sprite_index):
    """获取指定立绘的语音路径"""
    if not character_name or sprite_index is None:
        return None,""
    
    # 找到对应的角色
    character = next((c for c in characters if c["name"] == character_name), None)
    if not character or not character["sprites"] or sprite_index >= len(character["sprites"]):
        return None,""
    
    # 返回语音路径
    return character["sprites"][sprite_index].get("voice_path", None), character["sprites"][sprite_index].get("voice_path", "") 

def launch_chat(template, voice_mode, init_sprite_path):
    global main_process
    print("启动聊天，使用模板:")
    try:
        dest_path = os.path.join(TEMPLATE_DIR_PATH,'_temp.txt')
        with open(dest_path, mode='+wt',encoding="utf-8") as file:
            file.write(template)

        voice_mode = 'gen' if voice_mode == '全语音模式' else 'preset'
        init_path = init_sprite_path[0] if init_sprite_path else ''

        if main_process is None or main_process.poll() is not None:
            # 计算模板内容的哈希值（使用 SHA256 算法）
            template_hash = hashlib.md5(template.encode('utf-8')).hexdigest()
            history_filename = f"{template_hash}.json"
            main_process = subprocess.Popen(
                ['./runtime/python.exe', 
                 'main_sprite.py', 
                 '--template=_temp', 
                 f'--voice_mode={voice_mode}',
                 f'--init_sprite_path={init_path}',
                 f'--history={history_filename}',
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

def update_llm_info(llm_provider):
    """更新LLM信息"""
    global api_config
    llm_model_map = api_config.get("llm_model",{})
    llm_api_map = api_config.get("llm_api_key",{})
    return LLM_BASE_URLS.get(llm_provider, ""), llm_model_map.get(llm_provider,""), llm_api_map.get(llm_provider,"")

# 创建界面
with gr.Blocks(title="新世界程序") as demo:
    load_characters_from_file()
    load_api_config_from_file()
    gr.Markdown("# 新世界程序")
    gr.Markdown('''
    - （b站、小红书）作者：不二咲爱笑 
    - github: https://github.com/RachelForster/Shinsekai qq交流群：1033281516、本软件是开源软件，禁止商用
    ''')
    with gr.Tab("API 设定"):
        gr.Markdown("## API 配置")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### LLM API 配置")
                llm_provider = gr.Dropdown(
                    choices=list(LLM_BASE_URLS.keys()),
                    label="选择大语言模型供应商",
                    value=api_config.get("llm_provider", "Deepseek")
                )
                llm_provider_value = api_config.get("llm_provider","Deepseek")
                llm_model = gr.Textbox(label="模型ID", value=api_config.get("llm_model", "").get(llm_provider_value,""))
                api_key = gr.Textbox(label="LLM API Key", type="password", value=api_config.get("llm_api_key", {}).get(llm_provider_value,""))
                base_url = gr.Textbox(label="LLM API 基础网址", value=api_config.get("llm_base_url", ""))
            with gr.Column():
                    api_output = gr.Textbox(label="输出信息", interactive=False)
        with gr.Row():
            with gr.Column():
                gr.Markdown("### GPT SoVITS API 配置，如果没有可以不填，如果你想让角色读出台词，就需要配置")
                gr.Markdown("#### 前提条件")
                gr.Markdown('''
                1. 你的GPU大于等于6G
                2. 下载好GPT-SOVITS整合包
                ''')
                sovits_url = gr.Textbox(label="GPT-SoVITS API 调用地址", value=api_config.get("gpt_sovits_url", ""))
                gpt_sovits_api_path = gr.Textbox(label="GPT-SoVITS 服务启动路径", value=api_config.get("gpt_sovits_api_path", ""))
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
            update_llm_info,
            inputs=llm_provider,
            outputs=[base_url,llm_model,api_key]
        )

        save_api_btn.click(
            save_api_config,
            inputs=[llm_provider, llm_model,api_key, base_url, sovits_url, gpt_sovits_api_path],
            outputs=api_output
        )

    active_character=gr.State("") #当前选中的人物名
    selected_sprite_index = gr.State(None)  # 存储当前选中的立绘索引
    init_sprite_path = gr.State("")

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
                export_btn = gr.Button("导出到./output文件夹")
                del_btn = gr.Button("删除人物")
                def update_character_dropdown():
                    print(["新角色"]+[c.get("name", "") for c in characters])
                    return gr.Dropdown(choices=["新角色"]+[c.get("name", "") for c in characters])
                
                def update_character_information(selected_character):
                    character = next((c for c in characters if c["name"] == selected_character), None)
                    if character == None:
                        return "","","","","","","","",""
                    return character["name"], character["color"], character["sprite_prefix"], character["gpt_model_path"], character["sovits_model_path"], character["refer_audio_path"], character["prompt_text"], character["prompt_lang"], character.get("character_setting","")
                
            with gr.Column():
                gr.Markdown("#### 从文件导入")
                import_file = gr.File(label="选择文件")
                import_btn = gr.Button("从文件导入人物")
                import_output = gr.Textbox("输出结果")

                def export_character(character_name):
                    character = next((c for c in characters if c["name"] == character_name), None)
                    if character is None:
                        return "人物不存在"
                    try:
                        output_path = Path('./output')
                        output_path.mkdir(parents=True,exist_ok=True)
                        character = CharacterConfig(
                            name = character["name"],
                            color=character["color"], 
                            sprite_prefix=character["sprite_prefix"],
                            gpt_model_path=character.get("gpt_model_path", ""), 
                            sovits_model_path=character.get("sovits_model_path",""), 
                            refer_audio_path=character.get("refer_audio_path",""), 
                            prompt_text=character.get("prompt_text",""), 
                            prompt_lang=character.get("prompt_lang",""),
                            sprites=character.get("sprites",[]),
                            emotion_tags=character.get("emotion_tags",""),
                            sprite_scale=character.get("sprite_scale", 1.0)
                        )
                        fu.export_character([character], output_path=f'./output/{character.name}.char')
                        return "导出成功"
                    except Exception as e:
                        return f"导出失败 {e}"
                    
                def import_character(file_path):
                    try:
                        fu.import_character(file_path)
                        load_characters_from_file()
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
            add_character,
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
            delete_character,
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
            generate_character_setting,
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

            with gr.Column():
                # 动态生成情绪标签输入框
                gr.Markdown("### 标注立绘情绪关键字")
                gr.Markdown(f"这些是{selected_character.value}的立绘，请你生成每张立绘的情绪关键字，格式为：立绘 1：xxx")
                emotion_inputs = gr.Textbox(label="情绪关键字描述：", lines=20)
                upload_emotion_btn=gr.Button("上传立绘标注")
            

            # 上传立绘事件
            upload_sprites_btn.click(
                upload_sprites,
                inputs=[selected_character, sprite_files, emotion_inputs],
                outputs=[upload_output, sprites_gallery, emotion_inputs]
            )

            upload_emotion_btn.click(
                upload_emotion_tags,
                inputs=[selected_character, emotion_inputs],
                outputs=[upload_output]
            )

            def get_sprite_scale(name):
                if not name:
                    return 1.0    
                character = next((c for c in characters if c["name"] == name), None)

                if character:
                    return character.get("sprite_scale", 1.0)
                else:
                    return 1.0
            
            # 当选择角色时更新立绘显示
            selected_character.change(
                get_character_sprites,
                inputs=[selected_character],
                outputs=[sprites_gallery, emotion_inputs, sprite_files]
            )

            #上传scale
            sprite_scale_save_btn.click(
                save_sprite_scale,
                inputs=[selected_character, sprite_scale],
                outputs=[upload_output]
            )

            selected_character.change(
                get_sprite_scale,
                inputs=[selected_character],
                outputs=[sprite_scale]
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
                sprite_voice_text = gr.Textbox(label="立绘语音内容，全语音模式需填写", interactive=True)
                
                upload_voice_btn = gr.Button("上传语音")
                voice_upload_output = gr.Textbox(label="上传结果")
                
                # 更新选中立绘信息
                def update_selected_sprite_info(character_name, sprite_index):
                    if not character_name or sprite_index is None:
                        return "未选择立绘", None, ""
                    
                    character = next((c for c in characters if c["name"] == character_name), None)
                    if not character or not character.get("sprites") or sprite_index >= len(character["sprites"]):
                        return "立绘不存在", None,""
                    
                    sprite = character["sprites"][sprite_index]
                    emotion_tag = sprite.get("emotion_tag", "")
                    voice_path = sprite.get("voice_path", "")
                    voice_text = sprite.get("voice_text", "")
                    
                    info = f"立绘 {sprite_index+1}: {emotion_tag}"
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
                    fn=upload_voice,
                    inputs=[selected_character, selected_sprite_index, voice_upload, sprite_voice_text],
                    outputs=[voice_upload_output, sprite_voice_player]
                ).then(
                    fn=update_selected_sprite_info,
                    inputs=[selected_character, selected_sprite_index],
                    outputs=[selected_sprite_info, sprite_voice_player, sprite_voice_text]
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
                    choices=[c.get("name", "") for c in characters]
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
                label="选择初始立绘图片",
            )
            upload_init_sprite_btn = gr.Button("确认选择")

        launch_btn = gr.Button("启动聊天")
        launch_output = gr.Textbox(label="启动结果")
        
        stop_btn = gr.Button("关闭聊天")


        # 动态更新角色选择下拉框
        def update_template_dropdown():
            template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
            return gr.Dropdown(choices=template_files)
        
        # 当角色列表更新时，更新复选框选项
        def update_character_selection():
            return gr.CheckboxGroup(choices=[c.get("name", "") for c in characters])
        
        generate_btn.click(
            generate_template,
            inputs=[selected_chars],
            outputs=[template_output, filename]
        )

        upload_init_sprite_btn.click(
            lambda file_path: (file_path,"选择成功"),
            inputs=[initial_sprite_files],
            outputs=[init_sprite_path, launch_output]
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
            inputs=[template_output, voice_mode, init_sprite_path],
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

if __name__ == "__main__":
    demo.launch()
from config.character_manager import ConfigManager

config_manager = ConfigManager()

class TemplateGenerator:
    def generate_chat_template(self, selected_characters, bg_name, use_effect, use_cg, use_llm_translation):
        if not selected_characters:
            return "请至少选择一个角色！", ""
        
        names = ""

        # 让同样的人物生成同样的模板，就会有一样的md5了，进而会有同样的聊天历史文件。
        selected_characters = sorted(selected_characters)

        for char_name in selected_characters:
            names += f"{char_name}，"

        USE_EFFECT_JSON_STATEMENT =  """"effect": "角色的特效名称（可选）,选择范围在 LEAVE, SHOCKED, DISAPPOINTED, ATTENTION 内","""
        USE_TRANSALTION_JSON_STATEMENT = """"translate": "该角色说的话的日文翻译","""
        template = f"你需要模拟一个RPG剧情对话系统，出场人物有：{names}以及其他相关人物，请根据剧情调度人物\n"

        template += f'''
    每次输出时，必须严格使用 JSON 格式，结构为：
    {{
    "dialog": [
        {{
        "character_name": "角色名",
        "sprite": "str, 对应的立绘ID字符串，例如 01, 02",
        "speech": "该角色说的中文台词",
        {USE_EFFECT_JSON_STATEMENT if use_effect else None}
        {USE_TRANSALTION_JSON_STATEMENT if use_llm_translation else None}
        }}
    ]
    }}
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

        REQUIREMENTS = [
    "格式严格：输出内容必须严格且仅为 JSON 格式，不得包含任何附加的解释、说明或问候语。",
    
    f"角色名限制：character_name 字段只能是以下之一：{names} 或者固定关键字：旁白、选项、数值{"、场景" if bg_name else ''}{"、bgm" if bg_name else ''}{"、CG" if use_cg else ''}。",
    
    "立绘规范：sprite 字段必须填写一个两位数字代号（例如 01, 02），并根据当前台词语气和情绪自动选择最合适的立绘。",
    "非立绘角色：当 character_name 为 旁白、数值 或 选项 时，sprite 字段必须固定为 -1。",
    
    "场景切换：当 character_name 为 场景 时，sprite 填写场景编号，表示切换场景。该元素必须作为 dialog 数组中的第一个元素出现。其他字段为空。",
    "BGM 切换：当 character_name 为 bgm 时，sprite 填写 BGM 编号，表示切换bgm。应根据当前氛围进行切换，但不得过于频繁。其他字段为空。",

    "台词风格：speech 字段必须是角色的中文台词，内容和表达方式必须严格符合角色的个性、说话风格和背景设定。",
    "数组结构：所有对话和事件必须按时间顺序放入 dialog 数组中，数组中必须包含至少两个元素。",
    "旁白用途：旁白元素用于描写场景变化、人物动作和环境气氛。",
    
    "选项位置：dialog 数组的最后一个元素必须是选项。",
    "选项格式：选项内容在 speech 内，所有选项用 '/' 分隔。选项必须是用户可选择的对话或行为的纯文本描述，不得包含任何多余的描述或说明。",
    "选项平衡：选项必须包括：一个纯粹的插科打诨/无厘头选项、一个精明/理智的选项、以及一个中庸的选项。所有选项必须与当前的剧情紧密关联，并符合人物性格。",
    
    "数值显示：数值元素表示当前用户状态或者角色状态数值，或者当前任务，该元素要求出现在dialog数组的前部，当 character_name 为 数值 时，speech 内使用富文本格式（如 <span style='color:xxxx;'>HP：100</span>）。颜色应选择浅色系，符合马卡龙配色。多个数值用 <br> 分隔。",
]       
        if use_cg:
            REQUIREMENTS.append("CG 生成：在剧情关键节点或情感高潮时，将character_name 设置为CG，speech 内容必须是用于 Stable Diffusion 生成图片的 Prompt，必须在开头加入 highres, 8k, bestscores 等质量关键字，描述人数，例如1girl，并详细描述人物名称，例如nanami chiaki、人物发型发色，以及眼睛颜色、服装、表情、动作和环境。可以加入和viewer的互动，例如looking at the viewer")       
        if use_llm_translation:
            REQUIREMENTS.append("翻译字段：translate字段必须为角色台词 speech 的日文翻译，请将角色的台词翻译为日文，而不要将角色的动作翻译出来")
        if use_effect:
            REQUIREMENTS.append("特效使用：effect 字段为可选，值必须在 LEAVE、SHOCKED、DISAPPOINTED、ATTENTION 范围内。LEAVE是人物离场，无特效需求时，必须省略此字段。")
        template += "要求：\n"
        index = 1
        for item in REQUIREMENTS:
            template += f"{index}、{item}\n"
            index += 1
        template += f"\n请开始对话，开始时介绍下用户所处的情境和背景，{"设置初始的场景和bgm，" if bg_name and bg_name !="透明背景" else ''}以及在做什么事情：\n"
        return template, ""
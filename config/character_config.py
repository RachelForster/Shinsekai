import yaml

class CharacterConfig:
    def __init__(self, name, color, sprite_prefix, gpt_model_path=None, sovits_model_path=None, refer_audio_path=None, prompt_text=None, prompt_lang=None, sprites=[], emotion_tags="", sprite_scale = 1.0, character_setting=""):
        # 角色基本信息  
        self.name = name
        self.color = color
        self.sprite_prefix = sprite_prefix
        self.sprites = sprites
        self.character_setting = character_setting
        self.sprite_scale = sprite_scale
        self.emotion_tags = emotion_tags
    
        # gpt-sovits 语音配置
        self.gpt_model_path = gpt_model_path
        self.sovits_model_path = sovits_model_path
        self.refer_audio_path = refer_audio_path
        self.prompt_text = prompt_text
        self.prompt_lang = prompt_lang
       

    @staticmethod
    def read_from_files(path):
        """
        从YAML文件中读取角色配置并返回CharacterConfig对象列表。
        
        Args:
            path (str): YAML配置文件的路径
            
        Returns:
            list[CharacterConfig]: 包含所有角色配置的列表
        """
        with open(path, 'r', encoding='utf-8') as file:
            config_data = yaml.safe_load(file)
        
        characters = []
        for char_data in config_data:
            # 确保必需的字段存在
            if not all(key in char_data for key in ['name', 'color', 'sprite_prefix']):
                raise ValueError("YAML配置缺少必需字段（name, color, sprite_prefix）")
            
            # 创建CharacterConfig对象
            character = CharacterConfig(
                name=char_data['name'],
                color=char_data['color'],
                sprite_prefix=char_data['sprite_prefix'],
                gpt_model_path=char_data.get('gpt_model_path'),
                sovits_model_path=char_data.get('sovits_model_path'),
                refer_audio_path=char_data.get('refer_audio_path'),
                prompt_text=char_data.get('prompt_text'),
                prompt_lang=char_data.get('prompt_lang'),
                sprites=char_data.get("sprites"),
                sprite_scale=char_data.get("sprite_scale",1.0),
                emotion_tags=char_data.get("emotion_tags",""),
                character_setting=char_data.get("character_setting",""),
            )
            characters.append(character)  
        return characters
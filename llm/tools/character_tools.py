from llm.tools.tool_manager import ToolManager
from config.config_manager import ConfigManager

config_manager = ConfigManager()
tool_manager = ToolManager()


@tool_manager.tool
def get_character_info(character_name: str):
    """
    获取特定角色的详细背景设定、性格特点及立绘id和对应的情绪标注。
    当需要引入某个之前对话时没有遇到的新角色时调用。
    """
    char = config_manager.get_character_by_name(character_name)
    if not char:
        return {"error": f"找不到角色: {character_name}"}
    
    return {
        "name": char.name,
        "setting": char.character_setting,
        "emotion_tags": char.emotion_tags
    }

@tool_manager.tool
def get_character_list():
    """
    获取所有可用角色的列表。
    """
    return [char.name for char in config_manager.config.characters]
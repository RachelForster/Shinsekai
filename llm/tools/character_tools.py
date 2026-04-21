from llm.tools.tool_manager import ToolManager
from config.config_manager import ConfigManager

config_manager = ConfigManager()
tool_manager = ToolManager()


@tool_manager.tool
def get_character_info(character_name: str = ''):
    """
    获取特定角色的详细背景设定、性格特点及立绘id和对应的情绪标注。
    当你忘记了某个角色的设定和立绘时，可以调用这个工具来查询。输入角色名，输出该角色的详细信息。
    注意：调用时必须在 character_name 参数中提供角色姓名。
    """
    if not character_name or not character_name.strip():
        return {"error": "未提供角色名称。请先设定character_name参数，或调用 get_available_character_name_list 获取可用角色列表。"}
    char = config_manager.get_character_by_name(character_name)
    if not char:
        return {"error": f"找不到角色: {character_name}"}
    
    return {
        "name": char.name,
        "setting": char.character_setting,
        "emotion_tags": char.emotion_tags
    }

@tool_manager.tool
def get_available_character_name_list():
    """
    获取所有可用角色名字的列表。
    """
    return [char.name for char in config_manager.config.characters]
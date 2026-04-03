from llm.tools.tool_manager import ToolManager
from config.config_manager import ConfigManager

config_manager = ConfigManager()
tool_manager = ToolManager()
class CharacterTools:
    @tool_manager.tool
    def get_character_info(self, character_name: str):
        """
        获取特定角色的详细背景设定、性格特点及立绘的情绪标注。
        当需要引入某角色时调用。
        """
        char = config_manager.get_character_by_name(character_name)
        if not char:
            return {"error": f"找不到角色: {character_name}"}
        
        return {
            "name": char.name,
            "setting": char.character_setting,
            "emotion_tags": char.emotion_tags
        }
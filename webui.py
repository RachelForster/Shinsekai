import sys
from pathlib import Path

import gradio as gr

current_script = Path(__file__).resolve()
project_root = current_script.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from config.background_manager import BackgroundManager
from config.character_manager import CharacterManager
from config.config_manager import ConfigManager
from llm.template_generator import TemplateGenerator
from tools.generate_sprites import ImageGenerator
from ui.webui.api_tab import register_api_tab
from ui.webui.background_tab import register_background_tab
from ui.webui.character_tab import register_character_tab
from ui.webui.context import WebUIContext
from ui.webui.music_cover_tab import register_music_cover_tab
from ui.webui.template_tab import register_template_tab
from ui.webui.tools_tab import register_tools_tab

config_manager = ConfigManager()
character_manager = CharacterManager()
background_manager = BackgroundManager()
image_generator = ImageGenerator()
template_generator = TemplateGenerator()

ctx = WebUIContext(
    config_manager=config_manager,
    character_manager=character_manager,
    background_manager=background_manager,
    image_generator=image_generator,
    template_generator=template_generator,
    template_dir_path="./data/character_templates",
    history_dir="./data/chat_history",
)

with gr.Blocks(title="新世界程序") as demo:
    gr.Markdown("# 新世界程序")
    gr.Markdown(
        """
    - （b站、小红书）作者：不二咲爱笑
    - github: https://github.com/RachelForster/Shinsekai qq交流群：1033281516、本软件是开源软件，禁止商用
    """
    )

    register_api_tab(ctx)

    active_character = gr.State("")
    selected_sprite_index = gr.State(None)
    selected_bg_index = gr.State(None)
    init_sprite_path = gr.State("")
    history_file_path = gr.State("")
    character_name_list_len = gr.State(0)
    background_name_list_len = gr.State(0)

    register_character_tab(ctx, character_name_list_len, selected_sprite_index)
    register_background_tab(ctx, background_name_list_len, selected_bg_index)
    register_template_tab(ctx, character_name_list_len, background_name_list_len)
    register_music_cover_tab(ctx)
    register_tools_tab(ctx, character_name_list_len)

if __name__ == "__main__":
    demo.launch()

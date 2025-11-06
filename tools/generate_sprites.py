from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO
import sys
from typing import Union, List, Dict, Any
import json
from pathlib import Path
from PIL import Image
# 获取当前脚本的绝对路径
current_script = Path(__file__).resolve()
project_root = current_script.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from config.config_manager import ConfigManager

config = ConfigManager()
IMAGE_MODEL = 'gemini-2.5-flash-image'
PROMPT_GENERATION_MODEL = "gemini-2.5-flash" 
# 或者 "gemini-2.5-flash"

class ImageGenerator:
    def __init__(self):
        try:
            API_KEY = config.config.api_config.llm_api_key.get("Gemini", "")
            self.client = genai.Client(api_key=API_KEY)
        except Exception as e:
            print("没有设置Gemini的api key!")

    def generate_prompts(
        self,
        num_sprite: int,
        character_settings: str
    ) -> List[str]:
        """
        根据角色设定生成用于立绘制作的文本提示词列表，返回格式为 JSON 数组。

        Args:
            client: 初始化的 genai.Client 实例。
            character_settings: 角色信息

        Returns:
            一个包含多个文本提示词字符串的列表 (list[str])。
        """
        
        # 将角色设定转换为易于模型理解的字符串
        settings_str = character_settings

        # 构造系统指令和用户提示
        system_instruction = (
            "你是一名专业艺术家和提示词工程师。你的任务是根据提供的角色设定，"
            f"生成 {num_sprite} 个高质量、详细的 Gemini Image 提示词，"
            "用于生成该角色的不同姿势的立绘。"
            "严格遵守以下要求："
            "1. 每个提示词必须是单独的一条字符串，包括人物的表情和动作,在提示词中加入保持背景纯白色。最终提示词会和一张参考图片一起输入，请假装参考图片存在，并让人物做出一定的表情和姿势"
            "2. 你的最终输出必须是一个可解析的 JSON 数组 (JSON Array of Strings)，"
            "   不包含任何额外的解释或文本，例如：[\"prompt 1\", \"prompt 2\", ...]。"
            "3. 生成的提示词必须符合人物的性格和背景，不允许出现OOC（Out of Character）的情况"
        )

        user_prompt = (
            f"请根据以下角色设定，生成 {num_sprite} 个高质量的图像生成提示词：\n\n"
            f"--- 角色设定 ---\n{settings_str}\n\n"
            f"--- 提示词格式要求 ---\n"
            f"输出格式必须是严格的 JSON 字符串数组，每个字符串包括人物的表情和动作，保持背景纯白色"
        )
        
        print("-> 正在生成立绘提示词...")

        try:
            # 使用 generate_content 并强制 JSON 输出
            response = self.client.models.generate_content(
                model=PROMPT_GENERATION_MODEL,
                contents=[user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    # 强制模型输出 mime_type 为 application/json 的内容
                    response_mime_type="application/json", 
                ),
            )

            # 检查并解析 JSON 字符串
            if response.text:
                # 移除可能存在的 Markdown 标记，确保纯 JSON
                json_text = response.text.strip().replace("```json", "").replace("```", "").strip()
                
                # 解析 JSON 数组
                prompts_list = json.loads(json_text)
                
                if isinstance(prompts_list, list) and all(isinstance(p, str) for p in prompts_list):
                    print(f"-> 成功生成 {len(prompts_list)} 条提示词。")
                    return prompts_list
                else:
                    print("-> 警告：模型返回的 JSON 结构不正确（非字符串数组）。")
                    return [json_text] # 如果解析失败，返回原始文本以便调试
            else:
                print("-> 警告：模型未返回任何文本。")
                return []

        except json.JSONDecodeError as e:
            print(f"-> 错误：JSON 解析失败。请检查模型输出是否为有效的 JSON 数组。错误: {e}")
            print(f"-> 模型原始输出: {response.text}")
            return []
        except Exception as e:
            print(f"-> 错误：提示词生成失败。{e}")
            return []

    def generate_picture_with_reference(
        self,
        image_path: Union[str, Path], # 新增：参考图片路径
        prompt: str,
        output_file: Union[str, Path]
    ):
        """
        使用 gemini-2.5-flash-image 模型生成单张图片，并包含一张参考图片。

        Args:
            client: 初始化的 genai.Client 实例。
            image_path: 初始参考图片的路径 (例如 'reference/base_character.png')。
            prompt: 用于指导模型如何使用参考图片生成立绘的文本描述（例如：“Keep the character’s face and outfit from the reference image, but change the background to a sci-fi city.”）。
            output_file: 图片保存路径和文件名。
        """
        try:
            # 1. 加载参考图片
            print(f"-> 正在加载参考图片: {image_path}")
            ref_image = Image.open(image_path)

            # 2. 构造 contents 列表：同时包含文本和图片
            # 传入的 contents 列表中可以包含多个 Part，其中一个是图片，一个是文本
            contents = [
                prompt,
                ref_image  # PIL Image 对象可以直接作为内容传入
            ]
            
            print(f"-> 正在为 prompt: '{prompt[:50]}...' 生成图片...")

            # 3. 调用 generate_content 方法（而不是 generate_images）
            # 当输入包含图片时，你需要使用 generate_content
            response = self.client.models.generate_content(
                model=IMAGE_MODEL,
                contents=contents,
            )

            # 4. 检查结果并保存图片
            if response.candidates and response.candidates[0].content.parts:
                # 找到输出中的图片部分 (part)
                generated_image_part = None
                for part in response.candidates[0].content.parts:
                    # 检查是否包含 inline_data (Base64 编码的图片数据)
                    if part.inline_data is not None and part.inline_data.mime_type.startswith('image/'):
                        generated_image_part = part
                        break
                
                if generated_image_part:
                    # 获取字节数据
                    image_bytes = generated_image_part.inline_data.data
                    
                    # 将字节数据写入文件
                    output_path = Path(output_file)
                    output_path.parent.mkdir(parents=True, exist_ok=True) # 确保目录存在
                    
                    # 使用 BytesIO 和 PIL Image 来保存，确保格式正确
                    output_image = Image.open(BytesIO(image_bytes))
                    output_image.save(output_path)

                    print(f"-> 成功生成并保存图片至: {output_path.resolve()}")
                    return output_path
                else:
                    print("-> 警告：模型未在响应中返回图片。")
                    # 如果模型返回了文本（例如，只是描述了图片），你可以在这里打印出来
                    # print(f"-> 模型返回的文本：{response.text}")
                    return None
            else:
                print("-> 警告：模型未返回任何有效的候选结果。")
                return None

        except Exception as e:
            print(f"-> 错误：生成图片失败。{e}")
            return None

    def generate_picture(
        self,
        prompt: str,
        output_file: Union[str, Path]
    ):
        """
        使用 gemini-2.5-flash-image 模型生成单张图片。

        Args:
            client: 初始化的 genai.Client 实例。
            prompt: 用于生成立绘的文本描述。
            output_file: 图片保存路径和文件名（例如 'output/sprite_01.png'）。
                        父目录必须存在。
        """
        print(f"-> 正在为 prompt: '{prompt[:50]}...' 生成图片...")
        try:
            # 调用模型生成图片
            result = self.client.models.generate_images(
                model=IMAGE_MODEL,
                prompt=prompt,
                config=dict(
                    number_of_images=1,  # 确保只生成一张
                    output_mime_type="image/png" # 设置输出格式
                )
            )

            # 检查结果并保存图片
            if result.generated_images:
                # 获取第一张生成的图片数据
                image_bytes = result.generated_images[0].image.image_bytes

                # 将字节数据写入文件
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True) # 确保目录存在
                with open(output_path, "wb") as f:
                    f.write(image_bytes)

                print(f"-> 成功生成并保存图片至: {output_path.resolve()}")
                return output_path
            else:
                print("-> 警告：模型未返回任何图片。")
                return None

        except Exception as e:
            print(f"-> 错误：生成图片失败。{e}")
            return None


    def batch_generate_sprites(
        self,
        image_path,
        prompt_list: List[str],
        output_dir: Union[str, Path]
    ):
        """
        批量生成立绘。

        Args:
            client: 初始化的 genai.Client 实例。
            prompt_list: 包含所有立绘描述的列表。
            output_dir: 批量图片保存的目录。
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        print(f"--- 开始批量生成立绘到目录: {output_path.resolve()} ---")

        generated_files = []
        for i, prompt in enumerate(prompt_list):
            # 构造输出文件名，例如: sprite_001.png, sprite_002.png...
            output_file = output_path / f"sprite_{i + 1:03d}.png"

            # 调用单张图片生成方法
            result_file = self.generate_picture_with_reference(image_path, prompt, output_file)
            if result_file:
                generated_files.append(result_file)

        print("--- 批量生成完成 ---")
        return generated_files

from google import genai
from PIL import Image
from io import BytesIO
from contextlib import ExitStack
from collections.abc import Sequence
import sys
import uuid
from typing import Union, List, Dict, Any
from pathlib import Path
from PIL import Image
# 获取当前脚本的绝对路径
current_script = Path(__file__).resolve()
project_root = current_script.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from config.config_manager import ConfigManager

config = ConfigManager()
IMAGE_MODEL = 'gemini-2.5-flash-image'

class ImageGenerator:
    def __init__(self):
        self.client = None

    def _image_client(self):
        if self.client is None:
            API_KEY = config.config.api_config.llm_api_key.get("Gemini", "")
            self.client = genai.Client(api_key=API_KEY)
        return self.client

    def generate_prompts(
        self,
        num_sprite: int,
        character_settings: str
    ) -> List[str]:
        """Compatibility entry point using the configured LLM."""
        from application.image_generation.prompts import generate_sprite_prompts

        return generate_sprite_prompts(
            config,
            character_name="",
            character_setting=character_settings,
            count=num_sprite,
        )

    def generate_picture_with_reference(
        self,
        image_path: Union[str, Path, Sequence[Union[str, Path]]],
        prompt: str,
        output_file: Union[str, Path]
    ):
        """
        使用 gemini-2.5-flash-image 模型生成单张图片，并包含有序参考图片。

        Args:
            client: 初始化的 genai.Client 实例。
            image_path: 初始参考图片的路径 (例如 'reference/base_character.png')。
            prompt: 用于指导模型如何使用参考图片生成立绘的文本描述（例如：“Keep the character’s face and outfit from the reference image, but change the background to a sci-fi city.”）。
            output_file: 图片保存路径和文件名。
        """
        try:
            # 1. 加载参考图片
            print(f"-> 正在加载参考图片: {image_path}")
            paths = [image_path] if isinstance(image_path, (str, Path)) else list(image_path)
            with ExitStack() as stack:
                contents = [prompt, *(stack.enter_context(Image.open(path)) for path in paths)]
                response = self._image_client().models.generate_content(model=IMAGE_MODEL, contents=contents)

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
            result = self._image_client().models.generate_images(
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
        batch_id = uuid.uuid4().hex[:12]
        for i, prompt in enumerate(prompt_list):
            # 构造输出文件名，例如: sprite_001.png, sprite_002.png...
            output_file = output_path / f"sprite_{batch_id}_{i + 1:03d}.png"

            # 调用单张图片生成方法
            result_file = self.generate_picture_with_reference(image_path, prompt, output_file)
            if result_file:
                generated_files.append(result_file)
            else:
                raise RuntimeError(f"Image generation returned no sprite for prompt {i + 1}")

        print("--- 批量生成完成 ---")
        return generated_files

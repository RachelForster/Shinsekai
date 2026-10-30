"""Shared local anime background removal for tools and generated sprites."""

from functools import lru_cache
from pathlib import Path
from threading import Lock
from uuid import uuid4


_inference_lock = Lock()


@lru_cache(maxsize=1)
def _anime_session():
    from rembg import new_session

    # H3 already occupies the GPU. Reuse one CPU session across subsequent frames.
    return new_session("isnet-anime", providers=["CPUExecutionProvider"])


def remove_background_image(image):
    """Reuse the CPU session for images and sequential video frames."""
    try:
        from rembg import remove
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "抠图需要 rembg 和 onnxruntime，请安装本地图像处理依赖"
        ) from exc

    with _inference_lock:
        return remove(image.convert("RGBA"), session=_anime_session()).convert("RGBA")


def ai_remove_background(input_path, output_path):
    """Write a transparent PNG atomically; let callers handle processing failures."""
    from PIL import Image

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{uuid4().hex}.png")
    try:
        with Image.open(input_path) as image:
            remove_background_image(image).save(temporary, "PNG")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output.as_posix()


def batch_remove_background(input_dir, output_dir=None):
    """
    Batch-process images in a directory, removing backgrounds.
    """
    import os
    import glob

    if output_dir is None or output_dir == "":
        output_dir = os.path.join(input_dir, "removed_backgrounds")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    supported_formats = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff", "*.webp"]

    image_files = []
    for fmt in supported_formats:
        image_files.extend(glob.glob(os.path.join(input_dir, fmt)))
        image_files.extend(glob.glob(os.path.join(input_dir, fmt.upper())))
    image_files = sorted(set(image_files))

    if not image_files:
        print(f"在目录 '{input_dir}' 中未找到支持的图片文件")
        return "未找到支持的图片文件"

    print(f"找到 {len(image_files)} 个图片文件，开始批量移除背景...")

    processed_count = 0
    error_count = 0

    for image_path in image_files:
        try:
            filename = os.path.basename(image_path)
            name, ext = os.path.splitext(filename)
            output_filename = f"{name}.png"
            output_path = os.path.join(output_dir, output_filename)
            ai_remove_background(image_path, output_path)
            processed_count += 1
            print(f"✓ 已处理: {filename} -> {output_filename}")
        except Exception as e:
            error_count += 1
            print(f"✗ 处理失败: {filename}，错误: {e}")

    print(f"批量处理完成，成功处理: {processed_count}，失败: {error_count}")
    return (
        f"成功处理: {processed_count}，失败: {error_count}，输出到目录： {output_dir}"
    )

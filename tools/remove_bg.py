"""Batch background-removal tool wrapping core.media.background_removal."""

from core.media.background_removal import (
    BackgroundRemover,
    MATTING_MODELS,
    _anime_session,
    ai_remove_background,
    background_remover,
    remove_background_image,
    validate_matting_model,
)

__all__ = [
    "BackgroundRemover",
    "MATTING_MODELS",
    "ai_remove_background",
    "background_remover",
    "batch_remove_background",
    "remove_background_image",
    "validate_matting_model",
]


def batch_remove_background(input_dir, output_dir=None):
    """
    Batch-process images in a directory, removing backgrounds.
    """
    import glob
    import os

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

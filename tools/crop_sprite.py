import os
import sys
import argparse
import stat
from pathlib import Path

if __package__ in {None, ""}:
    _source_root = Path(__file__).resolve().parent.parent
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from PIL import Image

from sdk.file_transactions import (
    atomic_binary_writer,
    file_snapshot_is_stable,
    open_binary_read_without_links,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from core.paths import (
    managed_child_path,
    project_root,
    require_directory_without_links,
    resolve_project_output_path,
    resolve_runtime_asset_read_path,
)

# ./runtime/python.exe ./tools/crop_sprite.py -x 0.6 -d "C:\输入目录" -o "输出目录"
def batch_crop_upper_half(factor, directory, output_dir=None):
    """
    批量截取图片的上半部分
    Args:
        factor (float): 截取比例因子 (0-1之间，如0.5表示截取上半部分)
        directory (str): 输入图片目录
        output_dir (str): 输出目录，如果为None则创建子目录
    """
    
    # 验证因子范围
    if not 0 < factor <= 1:
        return("错误：因子必须在0到1之间")
    
    root = project_root()
    input_path = resolve_runtime_asset_read_path(os.fspath(directory), root=root)
    if not input_path.is_dir():
        return f"错误：目录 '{input_path}' 不存在"
    input_path, input_identity, input_entries = (
        snapshot_directory_entries_without_links(
            input_path,
            field="sprite crop input directory",
        )
    )
    
    # 设置输出目录
    if output_dir is None or output_dir == '':
        output_dir = input_path / f"cropped_upper_{factor}"
    
    # 创建输出目录
    output_path = resolve_project_output_path(os.fspath(output_dir), root=root)
    output_path.mkdir(parents=True, exist_ok=True)
    output_path = require_directory_without_links(
        output_path,
        field="cropped sprite output directory",
    )
    output_identity = output_path.lstat()
    
    # 支持的图片格式
    supported_suffixes = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
    
    # 获取所有图片文件
    image_files = sorted(
        [
            (child, metadata)
            for child, metadata in input_entries
            if stat.S_ISREG(metadata.st_mode)
            and child.suffix.lower() in supported_suffixes
        ],
        key=lambda item: (item[0].name.casefold(), item[0].name),
    )
    
    if not image_files:
        print(f"在目录 '{directory}' 中未找到支持的图片文件")
        return False
    
    print(f"找到 {len(image_files)} 个图片文件")
    print(f"开始批量处理，截取上半部分 {factor*100}%...")
    
    processed_count = 0
    error_count = 0
    
    for image_path, image_identity in image_files:
        try:
            # 打开图片
            with (
                open_binary_read_without_links(
                    image_path,
                    expected_identity=image_identity,
                    expected_parent_identity=input_identity,
                ) as image_file,
                Image.open(image_file) as img,
            ):
                before = os.fstat(image_file.fileno())
                img.load()
                after = os.fstat(image_file.fileno())
                if not file_snapshot_is_stable(before, after):
                    raise PermissionError(
                        f"input image changed while it was being read: {image_path}"
                    )
                # 获取图片尺寸
                width, height = img.size
                
                # 计算截取高度
                crop_height = int(height * factor)
                
                # 定义截取区域 (left, upper, right, lower)
                crop_box = (0, 0, width, crop_height)
                
                # 截取图片
                cropped_img = img.crop(crop_box)
                
                # 生成输出文件名
                filename = image_path.name
                output_file = managed_child_path(
                    output_path,
                    filename,
                    field="cropped sprite filename",
                )
                
                # 保存图片
                image_format = (
                    Image.registered_extensions().get(output_file.suffix.lower())
                    or img.format
                    or "PNG"
                )
                with atomic_binary_writer(
                    output_file,
                    expected_parent_identity=output_identity,
                ) as output:
                    cropped_img.save(output, format=image_format)
                
                processed_count += 1
                print(f"✓ 已处理: {filename} -> {filename}")
                
        except Exception as e:
            error_count += 1
            print(f"✗ 处理失败: {image_path.name} - 错误: {str(e)}")

    require_directory_identity(
        input_path,
        input_identity,
        field="sprite crop input directory",
    )
    require_directory_identity(
        output_path,
        output_identity,
        field="cropped sprite output directory",
    )
    print(f"\n处理完成！")
    print(f"成功处理: {processed_count} 个文件")
    print(f"处理失败: {error_count} 个文件")
    return f"成功裁剪，输出目录: {output_path}"

def main():
    parser = argparse.ArgumentParser(description='批量截取图片的上半部分')
    parser.add_argument('-x', '--factor', type=float, required=True,
                       help='截取比例因子 (0-1之间，如0.5表示截取上半部分一半)')
    parser.add_argument('-d', '--directory', type=str, required=True,
                       help='输入图片目录路径')
    parser.add_argument('-o', '--output', type=str, default=None,
                       help='输出目录路径 (可选，默认为输入目录下的子目录)')
    
    args = parser.parse_args()
    
    success = batch_crop_upper_half(args.factor, args.directory, args.output)
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()

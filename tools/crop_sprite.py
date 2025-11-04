import os
import sys
import argparse
from PIL import Image
import glob

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
    
    # 检查目录是否存在
    if not os.path.exists(directory):
        return(f"错误：目录 '{directory}' 不存在")
        return False
    
    # 设置输出目录
    if output_dir is None or output_dir == '':
        output_dir = os.path.join(directory, f"cropped_upper_{factor}")
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 支持的图片格式
    supported_formats = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff', '*.webp']
    
    # 获取所有图片文件
    image_files = []
    for format in supported_formats:
        image_files.extend(glob.glob(os.path.join(directory, format)))
        image_files.extend(glob.glob(os.path.join(directory, format.upper())))
    
    if not image_files:
        print(f"在目录 '{directory}' 中未找到支持的图片文件")
        return False
    
    print(f"找到 {len(image_files)} 个图片文件")
    print(f"开始批量处理，截取上半部分 {factor*100}%...")
    
    processed_count = 0
    error_count = 0
    
    for image_path in image_files:
        try:
            # 打开图片
            with Image.open(image_path) as img:
                # 获取图片尺寸
                width, height = img.size
                
                # 计算截取高度
                crop_height = int(height * factor)
                
                # 定义截取区域 (left, upper, right, lower)
                crop_box = (0, 0, width, crop_height)
                
                # 截取图片
                cropped_img = img.crop(crop_box)
                
                # 生成输出文件名
                filename = os.path.basename(image_path)
                name, ext = os.path.splitext(filename)
                output_filename = f"{name}{ext}"
                output_path = os.path.join(output_dir, output_filename)
                
                # 保存图片
                cropped_img.save(output_path)
                
                processed_count += 1
                print(f"✓ 已处理: {filename} -> {output_filename}")
                
        except Exception as e:
            error_count += 1
            print(f"✗ 处理失败: {os.path.basename(image_path)} - 错误: {str(e)}")
    
    print(f"\n处理完成！")
    print(f"成功处理: {processed_count} 个文件")
    print(f"处理失败: {error_count} 个文件")
    return f"成功裁剪，输出目录: {output_dir}"
    
    return True

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
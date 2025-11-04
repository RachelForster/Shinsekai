

def ai_remove_background(input_path, output_path):
    """
    使用 rembg 库自动移除背景。
    """
    try:
        from rembg import remove
        from PIL import Image
        input_img = Image.open(input_path)
        # remove() 函数会自动识别前景（人物）并移除背景
        output_img = remove(input_img)
        
        output_img.save(output_path, "PNG")
        print(f"AI 自动移除背景完成，图片已保存到 {output_path}")

    except ModuleNotFoundError as me:
        print(f"请先pip install 相关的依赖 {me}")
    
    except Exception as e:
            print(f"处理出错：{e}, ")

def batch_remove_background(input_dir, output_dir=None):
    """
    批量处理目录中的图片，移除背景。
    """
    import os
    import glob

    if output_dir is None or output_dir == '':
        output_dir = os.path.join(input_dir, "removed_backgrounds")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 支持的图片格式
    supported_formats = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff', '*.webp']
    
    # 获取所有图片文件
    image_files = []
    for format in supported_formats:
        image_files.extend(glob.glob(os.path.join(input_dir, format)))
        image_files.extend(glob.glob(os.path.join(input_dir, format.upper())))
    
    if not image_files:
        print(f"在目录 '{input_dir}' 中未找到支持的图片文件")
        return f"未找到支持的图片文件"
    
    print(f"找到 {len(image_files)} 个图片文件，开始批量移除背景...")
    
    processed_count = 0
    error_count = 0
    
    for image_path in image_files:
        try:
            filename = os.path.basename(image_path)
            name, ext = os.path.splitext(filename)
            output_filename = f"{name}_ai_transparent{ext}" 
            output_path = os.path.join(output_dir, output_filename)
            ai_remove_background(image_path, output_path)
            processed_count += 1
            print(f"✓ 已处理: {filename} -> {output_filename}")
        except Exception as e:
            error_count += 1
            print(f"✗ 处理失败: {filename}，错误: {e}")

    print(f"批量处理完成，成功处理: {processed_count}，失败: {error_count}")
    return  f"成功处理: {processed_count}，失败: {error_count}，输出到目录： {output_dir}"
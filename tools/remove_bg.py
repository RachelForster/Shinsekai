import os
import stat
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _source_root = Path(__file__).resolve().parent.parent
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from core.file_transactions import (
    atomic_binary_writer,
    capture_directory_identity,
    file_snapshot_is_stable,
    open_binary_read_without_links,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from core.process_launch import capture_launch_file
from core.paths import (
    managed_child_path,
    project_root,
    require_directory_without_links,
    resolve_project_output_path,
    resolve_runtime_asset_read_path,
)


def ai_remove_background(
    input_path,
    output_path,
    *,
    expected_source_identity: os.stat_result | None = None,
    expected_source_parent_identity: os.stat_result | None = None,
    expected_destination_parent_identity: os.stat_result | None = None,
):
    """
    Use rembg with the isnet-anime model (optimised for anime-style sprites).
    """
    root = project_root()
    source = resolve_runtime_asset_read_path(os.fspath(input_path), root=root)
    target = resolve_project_output_path(os.fspath(output_path), root=root)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_snapshot = capture_launch_file(
        source,
        field="background removal input image",
    )
    if (
        expected_source_identity is not None
        and not file_snapshot_is_stable(
            expected_source_identity,
            source_snapshot.identity,
        )
    ):
        raise PermissionError(
            f"background removal input image identity changed: {source}"
        )
    if (
        expected_source_parent_identity is not None
        and not os.path.samestat(
            expected_source_parent_identity,
            source_snapshot.parent.identity,
        )
    ):
        raise PermissionError(
            f"background removal input directory identity changed: {source.parent}"
        )
    target_parent, target_parent_identity = capture_directory_identity(
        target.parent,
        field="background removal output directory",
    )
    if target.parent != target_parent:
        raise PermissionError("background removal output directory changed identity")
    if (
        expected_destination_parent_identity is not None
        and not os.path.samestat(
            expected_destination_parent_identity,
            target_parent_identity,
        )
    ):
        raise PermissionError(
            f"background removal output directory identity changed: {target.parent}"
        )
    try:
        from rembg import remove, new_session
        from PIL import Image
        with (
            open_binary_read_without_links(
                source,
                expected_identity=source_snapshot.identity,
                expected_parent_identity=source_snapshot.parent.identity,
            ) as input_file,
            Image.open(input_file) as input_img,
        ):
            before = os.fstat(input_file.fileno())
            input_img.load()
            after = os.fstat(input_file.fileno())
            if not file_snapshot_is_stable(before, after):
                raise PermissionError(
                    f"input image changed while it was being read: {source}"
                )
            session = new_session("isnet-anime")
            output_img = remove(input_img, session=session)

        with atomic_binary_writer(
            target,
            expected_parent_identity=target_parent_identity,
        ) as output:
            output_img.save(output, "PNG")
        print(f"AI 自动移除背景完成，图片已保存到 {target}")

    except ModuleNotFoundError as me:
        print(f"请先pip install 相关的依赖 {me}")
        raise

    except Exception as e:
        print(f"处理出错：{e}, ")
        raise


def batch_remove_background(input_dir, output_dir=None):
    """
    Batch-process images in a directory, removing backgrounds.
    """
    root = project_root()
    input_path = resolve_runtime_asset_read_path(os.fspath(input_dir), root=root)
    if not input_path.is_dir():
        raise NotADirectoryError(input_path)
    input_path, input_identity, input_entries = (
        snapshot_directory_entries_without_links(
            input_path,
            field="background removal input directory",
        )
    )

    if output_dir is None or output_dir == "":
        output_dir = input_path / "removed_backgrounds"

    output_path = resolve_project_output_path(os.fspath(output_dir), root=root)
    output_path.mkdir(parents=True, exist_ok=True)
    output_path = require_directory_without_links(
        output_path,
        field="background removal output directory",
    )
    output_identity = output_path.lstat()

    supported_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

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
        print(f"在目录 '{input_dir}' 中未找到支持的图片文件")
        return "未找到支持的图片文件"

    print(f"找到 {len(image_files)} 个图片文件，开始批量移除背景...")

    processed_count = 0
    error_count = 0

    for image_path, image_identity in image_files:
        filename = image_path.name
        try:
            output_file = managed_child_path(
                output_path,
                filename,
                field="background-removed sprite filename",
            )
            ai_remove_background(
                image_path,
                output_file,
                expected_source_identity=image_identity,
                expected_source_parent_identity=input_identity,
                expected_destination_parent_identity=output_identity,
            )
            processed_count += 1
            print(f"✓ 已处理: {filename} -> {filename}")
        except Exception as e:
            error_count += 1
            print(f"✗ 处理失败: {filename}，错误: {e}")

    require_directory_identity(
        input_path,
        input_identity,
        field="background removal input directory",
    )
    require_directory_identity(
        output_path,
        output_identity,
        field="background removal output directory",
    )
    print(f"批量处理完成，成功处理: {processed_count}，失败: {error_count}")
    return f"成功处理: {processed_count}，失败: {error_count}，输出到目录： {output_path}"

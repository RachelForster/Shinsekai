"""Shared local anime background removal for tools and generated sprites."""

from functools import lru_cache
from contextlib import contextmanager
import logging
from pathlib import Path
from threading import Lock
from uuid import uuid4


_inference_lock = Lock()
MATTING_MODELS = ("toonout", "isnet-anime")


def validate_matting_model(value):
    if value not in MATTING_MODELS:
        raise ValueError("抠图模型须为 toonout 或 isnet-anime")
    return value


class BackgroundRemover:
    """Resolve a model once per job; never switch models halfway through a video."""

    def __init__(self, model, alpha_matting):
        self.model = validate_matting_model(model)
        self.requested_model = model
        self.alpha_matting = alpha_matting
        self.session = None
        self.fallback_reason = None
        self.device = "cpu"
        self.initialized = False

    def __call__(self, image):
        if not self.initialized:
            self.initialized = True
            if self.model == "toonout":
                from core.media.toonout import ToonOutSession, ToonOutUnavailable

                try:
                    self.session = ToonOutSession()
                    self.device = self.session.device
                except ToonOutUnavailable as exc:
                    logging.getLogger(__name__).warning(
                        "ToonOut unavailable; using ISNet: %s", exc
                    )
                    self.model = "isnet-anime"
                    self.fallback_reason = "toonout-unavailable"
        if self.session is None:
            return remove_background_image(image, alpha_matting=self.alpha_matting)
        cutout = self.session(image)
        if self.alpha_matting:
            from core.media.alpha_matting import refine_alpha_edges

            return refine_alpha_edges(image, cutout.getchannel("A"))
        return cutout

    def metadata(self):
        return {
            "model": self.model,
            "requestedModel": self.requested_model,
            "device": self.device,
            **(
                {"fallbackReason": self.fallback_reason} if self.fallback_reason else {}
            ),
        }

    def close(self):
        if self.session is not None:
            self.session.close()


@contextmanager
def background_remover(*, model="toonout", alpha_matting=False):
    remover = BackgroundRemover(model, alpha_matting)
    try:
        yield remover
    finally:
        remover.close()


@lru_cache(maxsize=1)
def _anime_session():
    from rembg import new_session

    # H3 already occupies the GPU. Reuse one CPU session across subsequent frames.
    return new_session("isnet-anime", providers=["CPUExecutionProvider"])


def remove_background_image(image, *, alpha_matting=False):
    """Reuse the CPU session for images and sequential video frames."""
    try:
        from rembg import remove
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "抠图需要 rembg 和 onnxruntime，请安装本地图像处理依赖"
        ) from exc

    with _inference_lock:
        return remove(
            image.convert("RGBA"),
            session=_anime_session(),
            alpha_matting=alpha_matting,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10,
            alpha_matting_erode_size=3,
        ).convert("RGBA")


def ai_remove_background(
    input_path, output_path, *, model="isnet-anime", alpha_matting=False, metadata=None
):
    """Write a transparent PNG atomically; let callers handle processing failures."""
    from PIL import Image

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{uuid4().hex}.png")
    try:
        with background_remover(model=model, alpha_matting=alpha_matting) as remove:
            with Image.open(input_path) as image:
                remove(image).save(temporary, "PNG")
            if metadata is not None:
                metadata.update(remove.metadata())
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

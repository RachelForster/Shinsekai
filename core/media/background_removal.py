"""Shared local anime background removal for generated sprites and media tools."""

from contextlib import contextmanager
from functools import lru_cache
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

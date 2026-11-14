"""Read-only endpoint calibration for existing and newly generated transitions."""

from functools import lru_cache
from pathlib import Path

from core.sprite.selection import resolve_runtime_path


def _measure(image):
    import numpy as np
    from PIL import Image

    width, height = image.size
    thumbnail = image.convert("RGBA")
    thumbnail.thumbnail((256, 256), Image.Resampling.LANCZOS)
    sample = np.asarray(thumbnail)
    alpha = sample[..., 3]
    if (alpha < 16).mean() < 0.001:
        raise ValueError("Endpoint has no transparent background")
    foreground = alpha >= 128
    rows = np.flatnonzero(foreground.sum(axis=1) >= max(2, sample.shape[1] * 0.005))
    columns = np.flatnonzero(foreground.sum(axis=0) >= max(2, sample.shape[0] * 0.005))
    opaque = alpha >= 240
    if not len(rows) or not len(columns) or opaque.sum() < 32:
        raise ValueError("Endpoint has no measurable foreground")
    luma = sample[..., :3][opaque] @ np.array([0.2126, 0.7152, 0.0722])
    return {
        "width": width,
        "height": height,
        "bounds": [
            float(columns[0] / sample.shape[1]),
            float(rows[0] / sample.shape[0]),
            float((columns[-1] + 1) / sample.shape[1]),
            float((rows[-1] + 1) / sample.shape[0]),
        ],
        "luma": float(luma.mean()),
    }


@lru_cache(maxsize=256)
def _endpoints(path, mtime_ns, size):
    from PIL import Image, ImageOps

    path = Path(path)
    if path.suffix.lower() not in (".webm", ".mp4"):
        with Image.open(path) as image:
            metrics = _measure(ImageOps.exif_transpose(image))
        return metrics, metrics
    import av
    import numpy as np

    with av.open(str(path)) as container:
        if (
            not container.streams.video
            or (container.duration or 0) > 12.1 * av.time_base
        ):
            raise ValueError("Unsupported endpoint video")
        stream = container.streams.video[0]
        if (
            stream.width * stream.height > 2_097_152
            or stream.metadata.get("alpha_mode") != "1"
        ):
            raise ValueError("Unsupported endpoint canvas or alpha")
        decoder = av.CodecContext.create("libvpx-vp9", "r")
        first, last, count = None, None, 0
        for packet in container.demux(stream):
            for frame in decoder.decode(packet):
                count += 1
                if count > 721:
                    raise ValueError("Endpoint video is too long")
                if len(frame.planes) != 4:
                    raise ValueError("Decoder did not preserve alpha")
                # Preserve alpha independently of RGB conversion, including narrow canvases.
                plane = frame.planes[3]
                alpha = np.frombuffer(plane, dtype=np.uint8).reshape(
                    plane.height, plane.line_size
                )[: frame.height, : frame.width]
                image = Image.fromarray(
                    np.dstack((frame.to_ndarray(format="rgb24"), alpha))
                )
                if first is None:
                    first = _measure(image)
                last = image
        if first is None or last is None:
            raise ValueError("Empty endpoint video")
        return first, _measure(last)


def _read(path):
    resolved = resolve_runtime_path(str(path))
    stat = resolved.stat()
    return _endpoints(str(resolved), stat.st_mtime_ns, stat.st_size)


def transition_presentation(start, clip, end):
    """Metadata is optional: old/unsupported assets must remain playable unchanged."""
    try:
        before = _read(start)[1]
        first, last = _read(clip)
        after = _read(end)[0]
        return {"from": before, "first": first, "last": last, "to": after}
    except Exception:
        return None

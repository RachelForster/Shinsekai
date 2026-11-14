"""Bounded decoding for cached mouth clips and portrait references."""
from pathlib import Path
import json

import av
import numpy as np
from PIL import Image, ImageOps

from core.sprite.mouth.manifest import MAX_DURATION, MAX_FRAMES


def reference_image(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        if image.width * image.height > 8_388_608:
            raise ValueError("立绘超过 800 万像素，请缩小后制作口型")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        return np.array(background.convert("RGB"))


def video_frames(path):
    with av.open(str(path)) as source:
        stream = source.streams.video[0]
        rate = float(stream.average_rate or 24)
        if not 1 <= rate <= 60 or stream.width * stream.height > 2_097_152:
            raise ValueError("口型视频须为 1–60 FPS，画面不超过 200 万像素")
        transparent = stream.metadata.get("alpha_mode") == "1" and stream.codec_context.name == "vp9"
        if transparent:
            decoder = av.CodecContext.create("libvpx-vp9", "r")
            frames = (frame for packet in source.demux(stream) for frame in decoder.decode(packet))
        else:
            frames = source.decode(stream)
        first_time = None
        for index, frame in enumerate(frames):
            time_base = frame.time_base or stream.time_base
            timestamp = float(frame.pts * time_base) if frame.pts is not None and time_base else index / rate
            if first_time is None:
                first_time = timestamp
            timestamp -= first_time
            if index >= MAX_FRAMES or timestamp > MAX_DURATION:
                raise ValueError("动态立绘与说话视频均须在 12 秒、720 帧以内")
            if transparent:
                rgba = Image.fromarray(frame.to_ndarray(format="rgba"))
                background = Image.new("RGBA", rgba.size, "white")
                background.alpha_composite(rgba)
                image = np.asarray(background.convert("RGB"))
            else:
                image = frame.to_ndarray(format="rgb24")
            yield index, timestamp, rate, image


def mouth_frames(path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    images, previews = [], []
    for index, timestamp, rate, image in video_frames(path):
        if len(images) >= 180:
            raise ValueError("说话视频过长，请使用不超过 180 帧的短片")
        images.append(image)
        preview = Image.fromarray(image)
        preview.thumbnail((256, 256))
        preview.save(output / f"{index:03d}.jpg", quality=88)
        previews.append({"index": index, "time": timestamp, "path": f"frames/{index:03d}.jpg"})
    if len(images) < 3:
        raise ValueError("说话视频至少需要三帧")
    (output.parent / "frames.json").write_text(json.dumps({"fps": rate, "frames": previews}), encoding="utf-8")
    return images, previews

"""Stream anime matting to a verified, silent VP9 WebM with real alpha."""

from fractions import Fraction
from pathlib import Path
from uuid import uuid4


def _check_alpha(frame):
    alpha = frame.getchannel("A")
    histogram = alpha.histogram()
    pixels = frame.width * frame.height
    if sum(histogram[:16]) < pixels * 0.001 or sum(histogram[128:]) < pixels * 0.001:
        raise ValueError("视频帧未得到有效透明背景或人物，请检查抠图模型与原视频")


def verify_alpha_video(path: Path) -> int:
    import av
    from PIL import Image

    count = 0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        if stream.metadata.get("alpha_mode") != "1":
            raise ValueError("视频没有 Alpha 通道，不能保存为透明立绘")
        # FFmpeg's native VP9 decoder drops alpha; libvpx reads BlockAdditional.
        decoder = av.CodecContext.create("libvpx-vp9", "r")
        for packet in container.demux(stream):
            for frame in decoder.decode(packet):
                _check_alpha(Image.fromarray(frame.to_ndarray(format="rgba")))
                count += 1
    if count < 2:
        raise ValueError("动态立绘至少需要两帧画面")
    return count


def remove_video_background(
    source: Path, output: Path, *, matte, progress=None, playback_speed=1.0
) -> dict:
    import av
    import numpy as np

    if (
        isinstance(playback_speed, bool)
        or not isinstance(playback_speed, (int, float))
        or not 0.5 <= playback_speed <= 1
    ):
        raise ValueError("动作速度须为 0.5–1 倍")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{uuid4().hex}.webm")
    count = 0
    try:
        with av.open(str(source)) as container:
            if not container.streams.video:
                raise ValueError("生成结果没有视频画面")
            stream = container.streams.video[0]
            source_rate = Fraction(stream.average_rate or 24)
            if not 1 <= source_rate <= 60:
                raise ValueError("动态立绘视频帧率须为 1–60 FPS")
            rate = source_rate * Fraction(str(playback_speed))
            if stream.width * stream.height > 2_097_152:
                raise ValueError("动态立绘画面超过 200 万像素，请降低工作流分辨率")
            duration = float(container.duration or 0) / av.time_base
            if duration > 12.1:
                raise ValueError("动态立绘目前支持 12 秒内的短视频，请缩短工作流时长")
            if duration / playback_speed > 12.1:
                raise ValueError(
                    "放慢后的视频超过 12 秒，请缩短工作流时长或提高动作速度"
                )
            total = max(1, int(duration * source_rate))
            with av.open(str(temporary), "w", format="webm") as target:
                encoded = target.add_stream("libvpx-vp9", rate=rate)
                encoded.width, encoded.height = stream.width, stream.height
                encoded.pix_fmt = "yuva420p"
                encoded.options = {
                    "lossless": "1",
                    "auto-alt-ref": "0",
                    "deadline": "good",
                    "cpu-used": "4",
                }
                for frame in container.decode(stream):
                    count += 1
                    if count > int(12 * rate) + 1:
                        raise ValueError("动态立绘超过 12 秒，已停止处理")
                    image = matte(frame.to_image()).convert("RGBA")
                    if image.size != (stream.width, stream.height):
                        raise ValueError("抠图改变了视频画面尺寸")
                    _check_alpha(image)
                    for packet in encoded.encode(
                        av.VideoFrame.from_ndarray(np.asarray(image), format="rgba")
                    ):
                        target.mux(packet)
                    if progress:
                        progress(count, max(total, count))
                for packet in encoded.encode():
                    target.mux(packet)
        if verify_alpha_video(temporary) != count:
            raise ValueError("透明视频帧数校验失败")
        temporary.replace(output)
        return {
            "frameCount": count,
            "duration": float(count / rate),
            "alphaVerified": True,
            "playbackSpeed": float(playback_speed),
        }
    finally:
        temporary.unlink(missing_ok=True)

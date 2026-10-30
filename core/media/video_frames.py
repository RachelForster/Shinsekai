"""Extract a still image from a local video without loading the full clip into RAM."""

from __future__ import annotations

import math
from pathlib import Path


def extract_video_frame(
    video: Path, output: Path, seconds: float | None = None
) -> float:
    """Save the frame at ``seconds`` (the middle by default), returning its timestamp."""
    if seconds is not None and (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise ValueError("截帧时间必须是大于或等于 0 的秒数")
    try:
        import av
    except ImportError as exc:
        raise RuntimeError("视频截帧需要 PyAV，请安装当前版本的运行依赖（av）") from exc

    with av.open(str(video)) as container:
        if not container.streams.video:
            raise ValueError("生成结果没有视频画面，无法截帧")
        stream = container.streams.video[0]
        duration = (
            float(stream.duration * stream.time_base)
            if stream.duration is not None
            else float(container.duration / av.time_base) if container.duration else 0
        )
        if seconds is not None and duration and seconds > duration + 0.05:
            raise ValueError("截帧时间超出了视频长度")
        target = seconds if seconds is not None else duration / 2
        start = float((stream.start_time or 0) * stream.time_base)
        # Seek to the preceding keyframe, then decode forward to the selected frame.
        if target > 0:
            seek_time = min(target, max(0, duration - 0.1)) if duration else target
            container.seek(int((start + seek_time) / stream.time_base), stream=stream)
        chosen = None
        timestamp = 0.0
        for frame in container.decode(stream):
            chosen = frame
            timestamp = max(0.0, float(frame.time or 0) - start)
            if timestamp + 0.0001 >= target:
                break
        if chosen is None:
            raise ValueError("视频没有可读取的帧")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".frame.png")
        try:
            chosen.to_image().convert("RGB").save(temporary, format="PNG")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return timestamp

"""Prepare the latest shared frame and its comparison image for visual inference."""

from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO

from PIL import Image, ImageDraw

from core.perception.models import PerceptionFrame


def _open_frame(frame: PerceptionFrame) -> Image.Image:
    data = base64.b64decode(frame.to_data_url().split(",", 1)[1])
    with Image.open(BytesIO(data)) as image:
        return image.convert("RGB")


def prepare_screen_frame(
    frame: PerceptionFrame,
    previous: PerceptionFrame | None,
    max_side: int,
) -> tuple[PerceptionFrame, bool]:
    """Build one image with the earlier frame on the left and the current frame on the right."""
    if previous is None and 0 < max(frame.width, frame.height) <= max_side:
        return frame, False
    current = _open_frame(frame)
    current.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    compared = previous is not None and previous.image_base64 != frame.image_base64
    if compared and previous is not None:
        try:
            earlier = _open_frame(previous)
        except (OSError, ValueError):
            compared = False
        else:
            # Two half-area panels keep the collage close to a single frame's pixel budget.
            limit = round(max_side / 2**0.5)
            current.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            earlier.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            header = 18
            gap = 4
            right = earlier.width + gap
            collage = Image.new(
                "RGB", (right + current.width, header + max(earlier.height, current.height)), "#181818",
            )
            collage.paste(earlier, (0, header))
            collage.paste(current, (right, header))
            draw = ImageDraw.Draw(collage)
            draw.text((4, 3), "1 EARLIER", fill="white")
            draw.text((right + 4, 3), "2 NOW", fill="white")
            current = collage

    buffer = BytesIO()
    current.save(buffer, format="JPEG", quality=85)
    return replace(
        frame,
        image_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
        mime_type="image/jpeg",
        width=current.width,
        height=current.height,
    ), compared

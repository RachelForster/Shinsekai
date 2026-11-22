"""Align existing mouth artwork with a new animated portrait."""
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from core.sprite.mouth.detector import detect
from core.sprite.mouth.extraction import _aligned_face
from core.sprite.mouth.frames import reference_image, video_frames
from core.sprite.mouth.geometry import bounded_box, compose_pose, transform
from core.sprite.mouth.manifest import read_manifest, suggested_mouth_box
from core.sprite.mouth.tracking import track


def _corners(box):
    x0, y0, x1, y1 = box
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def _extent(points):
    return np.r_[points.min(axis=0), points.max(axis=0)]


def transfer(request, detector, progress):
    manifest_path = Path(request["profile"])
    profile = read_manifest(manifest_path)
    old_reference = reference_image(request["reference"])
    if old_reference.shape[:2] != (profile["height"], profile["width"]):
        raise ValueError("原立绘的取景尺寸与已保存的口型不一致")
    video = request["sourceVideo"]
    with_frames = video_frames(video)
    try:
        _, _, _, reference = next(with_frames)
    except StopIteration:
        raise ValueError("动态立绘没有可读取的画面") from None
    finally:
        with_frames.close()
    height, width = reference.shape[:2]
    source = detect(detector, old_reference, mouth=False, chin=False)
    target = detect(detector, reference, mouth=False, chin=False)
    points = target["keypoints"]
    matrix = _aligned_face(source["keypoints"], points)
    factor = np.hypot(*matrix[:, 0])
    if not .25 <= factor <= 4 or abs(np.arctan2(matrix[1, 0], matrix[0, 0])) > .45:
        raise ValueError("新动态立绘的人脸尺寸或角度变化过大")
    patch = profile["patchBox"]
    extent = _extent(transform(_corners(patch), matrix))
    if np.any(extent[:2] < 0) or np.any(extent[2:] > [width, height]):
        raise ValueError("对齐后的嘴部超出动态立绘画面")
    box = bounded_box(extent, width, height)
    x0, y0, x1, y1 = box
    output = Path(request["output"])
    output.mkdir(parents=True, exist_ok=True)
    local = matrix.copy()
    local[:, 2] = transform(patch[:2], matrix) - [x0, y0]
    for filename in profile["mouths"].values():
        with Image.open(manifest_path.parent / filename) as image:
            rgba = np.asarray(image.convert("RGBA"))
        warped = cv2.warpAffine(rgba, local, (x1 - x0, y1 - y0))
        Image.fromarray(warped).save(output / filename)

    # Map saved offsets and account for the new integer crop's rotation pivot.
    adjustment = profile["correction"]
    old_center = transform(_corners(patch).mean(axis=0), matrix)
    delta = old_center - _corners(box).mean(axis=0)
    rotation = cv2.getRotationMatrix2D((0, 0), -adjustment["rotation"], adjustment["scale"])[:, :2]
    offset = matrix[:, :2] @ [adjustment["offsetX"], adjustment["offsetY"]] + delta - rotation @ delta
    adjustment = {**adjustment, "offsetX": float(offset[0]), "offsetY": float(offset[1])}
    manual = profile.get("manual")
    dimensions = np.array([width, height])
    if manual:
        source_dimensions = np.array([profile["width"], profile["height"]])
        manual_box = transform(_corners(manual["mouthBox"]) * source_dimensions, matrix) / dimensions
        chin = transform(manual["chin"] * source_dimensions, matrix) / dimensions
        manual = {"mouthBox": np.clip(_extent(manual_box), 0, 1).tolist(), "chin": np.clip(chin, 0, 1).tolist()}
        points = points.copy()
        points[2, :2] = np.asarray(manual["chin"]) * dimensions
        points[2, 2] = 1
    suggested = manual or {
        "mouthBox": suggested_mouth_box(points, width, height),
        "chin": np.clip(points[2, :2] / dimensions, 0, 1).tolist(),
    }
    Image.fromarray(reference).save(output / "reference.png")
    metadata = {"width": width, "height": height, "bbox": target["bbox"].tolist(),
                "keypoints": points.tolist(), "suggestedManual": suggested}
    old = request.get("speechGeometry") or {}
    crop = old.get("speechCrop") or old.get("crop")
    if crop:
        previous_transform = old.get("speechTransform")
        metadata["speechCrop"] = crop
        metadata["speechTransform"] = (compose_pose(matrix, previous_transform) if previous_transform is not None else matrix).tolist()
    (output / "prepared.json").write_text(json.dumps(metadata), encoding="utf-8")
    trajectory = track(detector, video, reference, {**target, "keypoints": points}, progress=progress)
    profile.update(
        trajectory, width=width, height=height, patchBox=box,
        correction=adjustment, manual=manual, sourceFingerprint=request["sourceFingerprint"],
        anchors={"chin": points[2, :2].tolist()},
    )
    path = output / "manifest.json"
    path.write_text(json.dumps(profile, separators=(",", ":")), encoding="utf-8")
    read_manifest(path)
    return {"ready": True, "manifest": "manifest.json"}

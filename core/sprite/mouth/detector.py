"""Optional anime landmark model, loaded only by preprocessing workers."""
from pathlib import Path

import cv2
import numpy as np

from core.sprite.mouth.geometry import manual_prediction


def load_detector(model_dir, device="auto"):
    import torch
    from anime_face_detector.detector import LandmarkDetector

    torch.set_num_threads(4)
    cv2.setNumThreads(4)
    selected = "cuda:0" if device != "cpu" and torch.cuda.is_available() else "cpu"
    if device == "cuda" and selected == "cpu":
        raise ValueError("当前识别环境无法使用 CUDA，请切换为自动或 CPU")
    directory = Path(model_dir)

    def create(target):
        return LandmarkDetector(
            directory / "hrnetv2.safetensors", face_detector_name="yolov3",
            face_detector_checkpoint_path=directory / "yolov3.safetensors",
            device=target, flip_test=True,
        )

    try:
        return create(selected), selected
    except RuntimeError:
        if device != "auto" or selected == "cpu":
            raise
        torch.cuda.empty_cache()
        return create("cpu"), "cpu"


def _quality(prediction, *, mouth, chin):
    points = prediction["keypoints"]
    if not np.isfinite(points).all():
        return 0.
    eyes = [points[11:17], points[17:23]]
    left, right = [eye[:, :2].mean(axis=0) for eye in eyes]
    distance = np.linalg.norm(right - left)
    if distance < 4:
        return 0.
    scores = [points[23, 2], *(np.median(eye[:, 2]) for eye in eyes)]
    if chin:
        scores.append(points[2, 2])
    if mouth:
        lips = points[24:28, :2]
        span = np.linalg.norm(lips[2] - lips[0])
        if not .75 <= span <= 1.15 * distance:
            return 0.
        scores.extend(points[24:28, 2])
    return min(scores)


def detect(detector, image, *, boxes=None, manual=None, mouth=True, chin=True):
    height, width = image.shape[:2]
    if manual and "mouthBox" in manual and "chin" in manual:
        return manual_prediction(manual, width, height)
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    predictions = [item for item in detector(bgr, boxes=boxes) if item["bbox"][4] >= .5]
    predictions.sort(
        key=lambda item: float(item["bbox"][4]) * float(np.prod(item["bbox"][2:4] - item["bbox"][:2])),
        reverse=True,
    )
    for prediction in predictions:
        if _quality(prediction, mouth=mouth, chin=chin) >= .3:
            return prediction
        bbox = prediction["bbox"]
        size = bbox[2:4] - bbox[:2]
        center = (bbox[2:4] + bbox[:2]) / 2
        # Bangs and stylized jaws can bias the face box. Re-run only landmarks
        # on a few tighter and vertically shifted views of the same face.
        alternatives = []
        for scale, shift in [(1., .08), (.88, .06), (.86, -.03), (1., -.08)]:
            middle = center + [0, size[1] * shift]
            half = size * scale / 2
            alternatives.append(np.r_[middle - half, middle + half, bbox[4]])
        refined = max(
            detector(bgr, boxes=alternatives),
            key=lambda item: _quality(item, mouth=mouth, chin=chin),
            default=None,
        )
        if refined is not None and _quality(refined, mouth=mouth, chin=chin) >= .3:
            return {**refined, "bbox": bbox}
    raise ValueError("脸部定位不可靠，请在预览中标出嘴部范围和下巴后重试")

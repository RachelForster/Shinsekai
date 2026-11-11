"""Geometry shared by extraction and tracking; imports stay in the worker."""
import cv2
import numpy as np


def stable_points(keypoints):
    return np.array([
        keypoints[11:17, :2].mean(axis=0),
        keypoints[17:23, :2].mean(axis=0), keypoints[23, :2],
    ], dtype=np.float32)


def stable_confidences(keypoints):
    return np.array([np.median(keypoints[11:17, 2]), np.median(keypoints[17:23, 2]), keypoints[23, 2]])


def transform(points, matrix):
    return np.asarray(points) @ matrix[:, :2].T + matrix[:, 2]


def compose_pose(outer, inner):
    outer, inner = np.asarray(outer), np.asarray(inner)
    return np.column_stack([outer[:, :2] @ inner[:, :2], transform(inner[:, 2], outer)])


def fit_pose(source, target):
    matrix, _ = cv2.estimateAffinePartial2D(
        np.asarray(source, np.float32), np.asarray(target, np.float32), method=cv2.LMEDS,
    )
    if matrix is None or not np.isfinite(matrix).all():
        raise ValueError("无法对齐人脸，请检查或手动调整嘴部与下巴位置")
    return matrix


def canvas_matrix(matrix):
    return [float(matrix[0, 0]), float(matrix[1, 0]), float(matrix[0, 1]), float(matrix[1, 1]), float(matrix[0, 2]), float(matrix[1, 2])]


def bounded_box(box, width, height):
    x0, y0, x1, y1 = box
    return [max(0, int(x0)), max(0, int(y0)), min(width, int(np.ceil(x1))), min(height, int(np.ceil(y1)))]


def manual_points(prediction, manual, width, height):
    if not manual:
        return prediction
    points = prediction["keypoints"].copy()
    if "mouthBox" in manual:
        x0, y0, x1, y1 = manual["mouthBox"]
        x0, x1, y0, y1 = x0 * width, x1 * width, y0 * height, y1 * height
        points[24:28] = [[x0, (y0 + y1) / 2, 1], [(x0 + x1) / 2, y0, 1], [x1, (y0 + y1) / 2, 1], [(x0 + x1) / 2, y1, 1]]
    if "chin" in manual:
        x, y = manual["chin"]
        points[2] = [x * width, y * height, 1]
    return {**prediction, "keypoints": points}


def manual_face_box(manual, width, height):
    if not manual or "mouthBox" not in manual or "chin" not in manual:
        return None
    x0, y0, x1, y1 = manual["mouthBox"]
    cx, cy = (x0 + x1) * width / 2, (y0 + y1) * height / 2
    span = max((x1 - x0) * width, 4)
    distance = max(manual["chin"][1] * height - cy, span * .5)
    return np.array([*bounded_box([cx - span * 3, cy - distance * 4, cx + span * 3, cy + distance * 1.5], width, height), 1], np.float32)


def manual_prediction(manual, width, height):
    """User anchors are authoritative; synthetic helpers only size tracking ROIs."""
    box = manual_face_box(manual, width, height)
    if box is None:
        raise ValueError("请同时标定嘴部范围和下巴")
    x0, y0, x1, y1 = manual["mouthBox"]
    cx, cy = (x0 + x1) * width / 2, (y0 + y1) * height / 2
    span = max((x1 - x0) * width, 4)
    distance = max(manual["chin"][1] * height - cy, span * .5)
    points = np.zeros((28, 3), dtype=np.float32)
    points[:, :2] = [cx, cy]
    points[11:17, :2] = [max(0, cx - span), max(0, cy - distance * 1.5)]
    points[17:23, :2] = [min(width - 1, cx + span), max(0, cy - distance * 1.5)]
    points[23, :2] = [cx, max(0, cy - distance * .6)]
    return {**manual_points({"bbox": box, "keypoints": points}, manual, width, height), "manual": True}

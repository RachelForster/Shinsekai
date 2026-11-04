"""Choose three real generated mouth poses and crop a common alpha patch."""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from core.media.sprite_mouth.detector import detect
from core.media.sprite_mouth.geometry import compose_pose, fit_pose, stable_points, transform
from core.media.sprite_mouth.manifest import POSES


def choose_frames(ratios, confidences):
    values = np.asarray(ratios, float)
    indices = np.flatnonzero(np.isfinite(values))
    if len(indices) < 3:
        raise ValueError("没有足够可靠的嘴型帧")
    values = values[indices]
    # Seed by opening range: a long wide-open hold must not consume both
    # the half-open and open clusters in a short clip.
    centers = np.linspace(values.min(), values.max(), 3)
    for _ in range(30):
        labels = np.argmin(abs(values[:, None] - centers[None, :]), axis=1)
        if any(not np.any(labels == group) for group in range(3)):
            raise ValueError("说话视频缺少完整开合，请重绘或手动选择嘴型帧")
        updated = np.array([values[labels == group].mean() for group in range(3)])
        if np.allclose(updated, centers, atol=1e-6):
            break
        centers = updated
    ordered = np.sort(centers)
    if ordered[-1] - ordered[0] < .15 or np.min(np.diff(ordered)) < .05:
        raise ValueError("嘴部开合幅度不足，请重绘或手动选取三种嘴型")
    chosen = {}
    for pose, group in zip(POSES, np.argsort(centers)):
        candidates = np.flatnonzero(labels == group)
        score = abs(values[candidates] - np.median(values[candidates])) + .025 * (1 - np.asarray(confidences)[indices[candidates]])
        chosen[pose] = int(indices[candidates[np.argmin(score)]])
    return chosen


def _manual_alignment(crop, image_shape, speech_transform):
    x0, y0, x1, y1 = crop
    height, width = image_shape[:2]
    scale = min(width / (x1 - x0), height / (y1 - y0))
    offset_x = (width - (x1 - x0) * scale) / 2
    offset_y = (height - (y1 - y0) * scale) / 2
    matrix = np.array([[1 / scale, 0, x0 - offset_x / scale], [0, 1 / scale, y0 - offset_y / scale]], float)
    return compose_pose(speech_transform, matrix) if speech_transform is not None else matrix


def _aligned_face(points, target):
    source_anchors, target_anchors = stable_points(points), stable_points(target)
    matrix = fit_pose(source_anchors, target_anchors)
    distance = np.linalg.norm(target_anchors[1] - target_anchors[0])
    if np.linalg.norm(transform(source_anchors, matrix) - target_anchors, axis=1).max() > distance * .3:
        raise ValueError("说话画面的人脸与立绘取景差异过大")
    return matrix


def _interior_opening(image, points):
    """Measure a dark mouth interior when lip landmarks miss the opening."""
    left, top, right, bottom = points[24:28, :2]
    span = np.linalg.norm(right - left)
    if span < 6:
        return None, None
    x, y = (left + right) / 2
    x0 = max(0, round(x - span * .66))
    x1 = min(image.shape[1], round(x + span * .66) + 1)
    y0 = max(0, round(min(y - span * .4, top[1] - span * .1)))
    y1 = min(image.shape[0], round(max(y + span * 1.05, bottom[1] + span * .1)) + 1)
    _, chin_y, chin_score = points[2]
    if chin_score >= .3 and chin_y > y + span * .2:
        y1 = min(y1, round(chin_y + span * .12))
    if x1 <= x0 or y1 <= y0:
        return None, None
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
    skin = np.percentile(gray, 75)
    if skin < 60:
        return None, None
    dark = (gray < min(skin - 35, skin * .72)).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(dark)
    radius = max(1, round(span * .22))
    cx, cy = round(x) - x0, round(y) - y0
    near_center = labels[max(0, cy - radius):cy + radius + 1, max(0, cx - radius):cx + radius + 1]
    components = [
        label for label in np.unique(near_center)
        if label and stats[label, cv2.CC_STAT_WIDTH] >= span * .23 and stats[label, cv2.CC_STAT_AREA] >= span ** 2 * .025
    ]
    if not components:
        return 0., None
    lx, ly, width, height, _ = stats[max(components, key=lambda label: stats[label, cv2.CC_STAT_AREA])]
    # Use the component's vertical extent within the lip corners, limiting
    # the patch when the dark interior touches the outline of the jaw.
    x1 = min(x0 + lx + width, max(left[0], right[0]))
    x0 = max(x0 + lx, min(left[0], right[0]))
    y0 += ly
    return float(height / span), np.array([[x0, y0], [x1, y0], [x1, y0 + height], [x0, y0 + height]])


def _lower_face(points):
    left, right, nose = stable_points(points)
    eye_line = right - left
    eye_distance = np.linalg.norm(eye_line)
    if eye_distance < 4 or points[23, 2] < .3:
        return None
    down = np.array([-eye_line[1], eye_line[0]]) / eye_distance
    depth = float((points[2, :2] - nose) @ down)
    if points[2, 2] < .3 or not .18 * eye_distance <= depth <= 1.5 * eye_distance:
        depth = None
    return nose, down, depth


def _within_lower_face(outline, lower_face):
    if lower_face is None:
        return True
    nose, down, depth = lower_face
    heights = (outline - nose) @ down
    top, bottom = heights.min(), heights.max()
    if depth is None:
        return top > 0
    # Keep some breathing room under the nose and limit aperture relative
    # to the character's face, so a narrow O shape can still be selected.
    return top >= .04 * depth and bottom <= depth and bottom - top <= .82 * depth


def extract(detector, images, reference, prediction, crop, output, *, selected=None, manual=None, speech_transform=None):
    output = Path(output)
    if selected is not None:
        if not isinstance(selected, dict) or set(selected) != set(POSES):
            raise ValueError("请分别选择闭合、半开和张开三帧")
        if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(images) for i in selected.values()):
            raise ValueError("选取的嘴型帧超出视频范围")
        if len(set(selected.values())) != 3:
            raise ValueError("三种嘴型应选择不同的帧")
    ratios, confidences = [None] * len(images), [0.] * len(images)
    matrices, mouth_points = {}, {}
    pixel_openings, pixel_outlines = [None] * len(images), {}
    target = prediction["keypoints"]
    target_lower_face = _lower_face(target) if selected is None and not manual else None
    rejected = 0
    boxes = None
    indices = sorted(selected.values()) if selected is not None else range(len(images))
    for index in indices:
        image = images[index]
        if manual and selected is not None:
            # With manual placement and frames, use the original speech crop.
            matrices[index] = _manual_alignment(crop, image.shape, speech_transform)
            mouth_points[index] = target[24:28, :2]
            continue
        try:
            try:
                source = detect(detector, image, boxes=boxes, chin=False)
            except ValueError:
                if boxes is None:
                    raise
                source = detect(detector, image, chin=False)
            points = source["keypoints"]
            matrix = _manual_alignment(crop, image.shape, speech_transform) if manual else _aligned_face(points, target)
        except ValueError:
            if selected is None:
                continue
            # The user's choice determines the pose. Align using eyes and nose
            # even when this frame's lip landmarks are too weak to classify it.
            try:
                points = detect(detector, image, mouth=False, chin=False)["keypoints"]
                matrices[index] = _aligned_face(points, target)
            except ValueError as error:
                raise ValueError(f"第 {index + 1} 帧无法与立绘对齐，请调整嘴部定位或改选此帧") from error
            continue
        lips = transform(points[24:28, :2], matrix)
        if selected is None:
            boxes = [source["bbox"]]
            opening, interior = _interior_opening(image, points)
            outline = points[24:28, :2] if interior is None else np.vstack([points[24:28, :2], interior])
            if target_lower_face is not None and target_lower_face[2] is not None:
                outline = transform(outline, matrix)
                bounds = target_lower_face
            else:
                bounds = _lower_face(points)
            if not _within_lower_face(outline, bounds):
                rejected += 1
                continue
            pixel_openings[index], pixel_outlines[index] = opening, interior
        matrices[index] = matrix
        mouth_points[index] = lips
        ratios[index] = float(np.linalg.norm(points[25, :2] - points[27, :2]) / max(np.linalg.norm(points[24, :2] - points[26, :2]), 1))
        confidences[index] = float(points[24:28, 2].mean())
    if selected is None:
        try:
            selected = choose_frames(ratios, confidences)
        except ValueError as landmark_error:
            try:
                selected = choose_frames(pixel_openings, confidences)
                closed, half, opened = (pixel_openings[selected[pose]] for pose in POSES)
                if not .24 <= (half - closed) / (opened - closed) <= .76:
                    raise landmark_error
            except ValueError:
                if rejected:
                    raise ValueError("已跳过嘴型超出正常范围的帧，剩余画面不足三档口型。请重新生成说话视频或手动选帧") from None
                raise landmark_error from None
            ratios = pixel_openings
            for index in selected.values():
                if pixel_outlines[index] is not None:
                    mouth_points[index] = np.vstack([mouth_points[index], transform(pixel_outlines[index], matrices[index])])
    height, width = reference.shape[:2]
    base = target[24:28, :2]
    if manual:
        x0, y0, x1, y1 = manual["mouthBox"]
        corners = np.array([[x0 * width, y0 * height], [x1 * width, y0 * height], [x1 * width, y1 * height], [x0 * width, y1 * height]])
        base = np.vstack([base, corners])
    outlines = [base, *(mouth_points[i] for i in selected.values() if i in mouth_points)]
    points = np.concatenate(outlines)
    span = max(float(np.ptp(item[:, 0])) for item in outlines)
    padding = max(2, round(span * .15))
    blur = max(.6, span * .035)
    margin = padding + np.ceil(3 * blur)
    x0, y0 = np.maximum(0, np.floor(points.min(axis=0) - margin)).astype(int).tolist()
    x1, y1 = np.minimum([width, height], np.ceil(points.max(axis=0) + margin + 1)).astype(int).tolist()
    patch_width, patch_height = x1 - x0, y1 - y0
    if patch_width <= 0 or patch_height <= 0:
        raise ValueError("没有识别到可裁剪的嘴部范围")
    if patch_width * patch_height > width * height * .3:
        raise ValueError("嘴部区域过大，请校准嘴部范围")
    origin = np.array([x0, y0])
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * padding + 1, 2 * padding + 1))
    for pose in POSES:
        index = selected[pose]
        # Keep a common playback box but only replace pixels around this
        # pose, so a wide-open pose cannot expose the jaw on closed frames.
        local_points = np.vstack([base, mouth_points[index]]) if index in mouth_points else points
        hull = cv2.convexHull(np.round(local_points - origin).astype(np.int32))
        mask = np.zeros((patch_height, patch_width), np.uint8)
        cv2.fillConvexPoly(mask, hull, 255)
        expanded = cv2.dilate(mask, kernel)
        alpha = np.maximum(mask, cv2.GaussianBlur(expanded, (0, 0), blur))
        matrix = matrices[index].copy()
        matrix[:, 2] -= origin
        aligned = cv2.warpAffine(images[index], matrix, (patch_width, patch_height))
        image = Image.fromarray(aligned).convert("RGBA")
        image.putalpha(Image.fromarray(alpha))
        image.save(output / f"mouth-{pose}.png")
    return {"patchBox": [x0, y0, x1, y1], "selectedFrames": selected, "openness": ratios, "confidences": confidences}

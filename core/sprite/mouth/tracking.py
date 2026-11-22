"""Track automatically initialized facial patches once, before playback."""
import cv2
import numpy as np

from core.sprite.mouth.detector import detect
from core.sprite.mouth.frames import video_frames
from core.sprite.mouth.geometry import canvas_matrix, stable_confidences, stable_points, transform


def _box(point, half, shape):
    height, width = shape[:2]
    x, y = point
    return [max(0, round(x - half[0])), max(0, round(y - half[1])), min(width, round(x + half[0] + 1)), min(height, round(y + half[1] + 1))]


def _match(gray, template, box, margin):
    x0, y0, x1, y1 = box
    sx, sy = max(0, x0 - margin), max(0, y0 - margin)
    search = gray[sy:min(gray.shape[0], y1 + margin), sx:min(gray.shape[1], x1 + margin)]
    values = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(values)
    dx = dy = 0.
    if 0 < x < values.shape[1] - 1:
        a, b, c = values[y, x - 1:x + 2]
        if abs(float(a - 2 * b + c)) > 1e-7:
            dx = float(np.clip(.5 * (a - c) / (a - 2 * b + c), -1, 1))
    if 0 < y < values.shape[0] - 1:
        a, b, c = values[y - 1:y + 2, x]
        if abs(float(a - 2 * b + c)) > 1e-7:
            dy = float(np.clip(.5 * (a - c) / (a - 2 * b + c), -1, 1))
    return np.array([sx + x + dx - x0, sy + y + dy - y0]), float(score)


def _face_motion(anchors, offsets, scores, eye_distance):
    keep = scores >= .65
    if np.count_nonzero(keep) < 2:
        return None
    anchors, offsets, scores = anchors[keep], offsets[keep], scores[keep]
    weights = scores ** 2
    center = np.average(anchors, axis=0, weights=weights)
    moved_center = center + np.average(offsets, axis=0, weights=weights)
    source = anchors - center
    moved = anchors + offsets - moved_center
    denominator = np.sum(weights * np.sum(source ** 2, axis=1))
    if denominator > 0:
        cosine = np.sum(weights * np.sum(source * moved, axis=1)) / denominator
        sine = np.sum(weights * (source[:, 0] * moved[:, 1] - source[:, 1] * moved[:, 0])) / denominator
        linear = np.array([[cosine, -sine], [sine, cosine]])
        matrix = np.column_stack([linear, moved_center - linear @ center])
        errors = np.linalg.norm(transform(anchors, matrix) - (anchors + offsets), axis=1)
        scale = np.hypot(cosine, sine)
        angle = np.arctan2(sine, cosine)
        if .8 <= scale <= 1.2 and abs(angle) <= .28 and max(errors) <= max(1.5, eye_distance * .05):
            return matrix, float(scores.min())
    # If a point slips, use translation from a pair that agrees instead of
    # rotating the patch to explain the bad match.
    pairs = [(i, j) for i in range(len(anchors)) for j in range(i + 1, len(anchors))]
    i, j = min(pairs, key=lambda pair: np.linalg.norm(offsets[pair[0]] - offsets[pair[1]]))
    if np.linalg.norm(offsets[i] - offsets[j]) > max(2., eye_distance * .08):
        return None
    shift = np.average(offsets[[i, j]], axis=0, weights=weights[[i, j]])
    return np.column_stack([np.eye(2), shift]), float(min(scores[i], scores[j]))


def _eyes_agree_with_nose(anchors, offsets, scores, eye_distance, last_linear):
    eyes = scores[:2] >= .65
    tolerance = max(1., eye_distance * .0175)
    if eyes.all():
        eye_motion = _face_motion(anchors[:2], offsets[:2], scores[:2], eye_distance)
        if eye_motion is None:
            return False
        nose_y = transform(anchors[2], eye_motion[0])[1]
        return abs(nose_y - anchors[2, 1] - offsets[2, 1]) <= tolerance
    # With only one eye, compare its movement relative to the nose in the last
    # reliable head pose. A blink can move the eyelid template while the head stays still.
    relative = anchors[:2] - anchors[2]
    expected_y = relative @ (last_linear[1] - [0., 1.])
    return np.any(eyes & (np.abs(offsets[:2, 1] - offsets[2, 1] - expected_y) <= tolerance))


def track(detector, source_video, reference, prediction, *, tracking_keypoints=None, progress=None):
    if source_video is None:
        return {"fps": 0, "duration": 0, "track": [{"time": 0, "matrix": [1, 0, 0, 1, 0, 0]}]}
    height, width = reference.shape[:2]
    scale = min(1., 832 / max(height, width))
    small = cv2.resize(reference, (round(width * scale), round(height * scale)))
    keypoints = prediction["keypoints"].copy()
    keypoints[:, :2] *= scale
    facial = keypoints
    if tracking_keypoints is not None:
        facial = np.asarray(tracking_keypoints, dtype=np.float32).copy()
        facial[:, :2] *= scale
    fixed = stable_points(facial)
    anchors = np.vstack([fixed, keypoints[2, :2]])
    distance = float(np.linalg.norm(fixed[0] - fixed[1]))
    halves = [(distance * .25, distance * .2)] * 2 + [(distance * .2, distance * .12), (distance * .26, distance * .12)]
    boxes = [_box(point, (max(3, half[0]), max(3, half[1])), small.shape) for point, half in zip(anchors, halves)]
    gray0 = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    templates = [gray0[y0:y1, x0:x1].copy() for x0, y0, x1, y1 in boxes]
    confidence = [*stable_confidences(facial), keypoints[2, 2]]
    usable = [score >= .3 and template.size >= 9 and template.std() >= 2 for score, template in zip(confidence, templates)]
    margin = max(6, round(distance * .4))
    matrices, timestamps, scores = [], [], []
    frame_rate = 24.
    for index, timestamp, frame_rate, image in video_frames(source_video):
        if image.shape[:2] != reference.shape[:2]:
            raise ValueError("动态立绘取景发生变化，请重新制作口型")
        image = cv2.resize(image, (small.shape[1], small.shape[0]))
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        matches = [
            _match(gray, templates[i], boxes[i], margin) if usable[i] else (np.zeros(2), 0.)
            for i in range(3)
        ]
        offsets, quality = (np.asarray(values) for values in zip(*matches))
        linear = matrices[-1][:, :2] if matrices else np.eye(2)
        if quality[2] >= .8 and not _eyes_agree_with_nose(fixed, offsets, quality, distance, linear):
            # Keep the previous scale and rotation through a blink, while the
            # nose still follows real head movement. Landmark fallback can also move with eyelids.
            nose = fixed[2]
            motion = np.column_stack([linear, nose + offsets[2] - linear @ nose]), float(quality[2])
        else:
            motion = _face_motion(fixed, offsets, quality, distance)
        if motion is None and detector is not None and sum(usable[:3]) >= 2:
            try:
                current = detect(detector, image, mouth=False, chin=False)["keypoints"]
                positions = stable_points(current)
                if np.linalg.norm(positions.mean(axis=0) - fixed.mean(axis=0)) <= margin * 1.5:
                    motion = _face_motion(fixed, positions - fixed, stable_confidences(current), distance)
            except ValueError:
                pass
        if motion is None and usable[3]:
            shift, score = _match(gray, templates[3], boxes[3], margin)
            if score >= .5:
                motion = np.column_stack([linear, anchors[3] + shift - linear @ anchors[3]]), score
        matrix, score = motion if motion is not None else (matrices[-1] if matrices else np.eye(2, 3), 0.)
        matrices.append(matrix)
        timestamps.append(timestamp)
        scores.append(score)
        if progress and index % 12 == 0:
            progress(f"正在匹配动态立绘，第 {index + 1} 帧")
    if not matrices:
        raise ValueError("动态立绘没有可读取的画面")
    if sum(score < .5 for score in scores) > len(scores) * .15:
        raise ValueError("脸部跟随不稳定，请将备用锚点放在清晰的下巴边缘，或换用头部更稳定的视频")
    matrices = np.array(matrices)
    padded = np.pad(matrices, ((2, 2), (0, 0), (0, 0)), mode="edge")
    matrices = sum(weight * padded[i:i + len(matrices)] for i, weight in enumerate([1/16, 4/16, 6/16, 4/16, 1/16]))
    matrices[:, :, 2] /= scale
    return {
        "fps": frame_rate, "duration": timestamps[-1] + 1 / frame_rate,
        "track": [{"time": timestamp, "matrix": canvas_matrix(matrix)} for timestamp, matrix in zip(timestamps, matrices)],
        "minimumConfidence": min(scores),
    }

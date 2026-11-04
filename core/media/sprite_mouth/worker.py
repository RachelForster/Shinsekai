"""Isolated optional-Python worker; exits before H3 generation to release VRAM."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(ROOT))
    if len(sys.argv) > 2:
        sys.path.insert(0, sys.argv[2])
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def emit(kind, **data):
    print("MOUTH_EVENT:" + json.dumps({"type": kind, **data}, ensure_ascii=True), flush=True)


def prepare(request, detector):
    import numpy as np
    from PIL import Image
    from core.media.sprite_mouth.detector import detect
    from core.media.sprite_mouth.frames import reference_image
    from core.media.sprite_mouth.geometry import bounded_box, stable_confidences
    from core.media.sprite_mouth.manifest import suggested_mouth_box

    output = Path(request["output"])
    output.mkdir(parents=True, exist_ok=True)
    image = reference_image(request["reference"])
    manual = request.get("manual")
    prediction = detect(detector, image, manual=manual, chin=False)
    height, width = image.shape[:2]
    x0, y0, x1, y1 = prediction["bbox"][:4]
    bw, bh = x1 - x0, y1 - y0
    crop = bounded_box([x0 - bw * .3, y0 - bh * .3, x1 + bw * .3, y1 + bh * .2], width, height)
    if crop[2] - crop[0] < 16 or crop[3] - crop[1] < 16:
        raise ValueError("识别到的人脸过小，请使用更清晰的立绘")
    Image.fromarray(image).save(output / "reference.png")
    Image.fromarray(image).crop(crop).save(output / "face-reference.png")
    points = prediction["keypoints"]
    suggested = manual or {
        "mouthBox": suggested_mouth_box(points, width, height),
        "chin": np.clip(points[2, :2] / [width, height], 0, 1).tolist(),
    }
    metadata = {"width": width, "height": height, "crop": crop, "speechCrop": request.get("speechCrop") or crop, "bbox": prediction["bbox"].tolist(), "keypoints": points.tolist(), "suggestedManual": suggested}
    if request.get("speechTransform") is not None:
        metadata["speechTransform"] = request["speechTransform"]
    if manual and request.get("trackingKeypoints") is not None:
        anchors = np.asarray(request["trackingKeypoints"], dtype=np.float32)
        if (
            anchors.shape == points.shape and np.isfinite(anchors).all()
            and np.count_nonzero(stable_confidences(anchors) >= .3) >= 2
        ):
            metadata["trackingKeypoints"] = anchors.tolist()
    (output / "prepared.json").write_text(json.dumps(metadata), encoding="utf-8")
    return {"ready": True, **metadata}


def analyze(request, detector, device):
    import numpy as np
    from core.media.sprite_mouth.extraction import extract
    from core.media.sprite_mouth.frames import reference_image, mouth_frames
    from core.media.sprite_mouth.manifest import correction, read_manifest
    from core.media.sprite_mouth.tracking import track

    output = Path(request["output"])
    metadata = json.loads((output / "prepared.json").read_text(encoding="utf-8"))
    image = reference_image(output / "reference.png")
    prediction = {"bbox": np.array(metadata["bbox"]), "keypoints": np.array(metadata["keypoints"])}
    frames, previews = mouth_frames(output / "speech.mp4", output / "frames")
    timing = json.loads((output / "frames.json").read_text(encoding="utf-8"))
    common = {"width": image.shape[1], "height": image.shape[0], "frames": previews, "speechFps": timing["fps"], "speechVideo": "speech.mp4", "reference": "reference.png", "suggestedManual": metadata["suggestedManual"], "device": device, "manual": request.get("manual"), "selectedFrames": request.get("selectedFrames"), "correction": correction(request.get("correction"))}
    emit("progress", message="正在识别并选取三种嘴型")
    extraction = None
    try:
        extraction = extract(
            detector, frames, image, prediction, metadata.get("speechCrop", metadata["crop"]), output,
            selected=request.get("selectedFrames"), manual=request.get("manual"), speech_transform=metadata.get("speechTransform"),
        )
        emit("progress", message="正在计算立绘的嘴部跟随轨迹")
        trajectory = track(
            detector, request.get("sourceVideo"), image, prediction,
            tracking_keypoints=metadata.get("trackingKeypoints"), progress=lambda message: emit("progress", message=message),
        )
    except ValueError as error:
        return {"ready": False, "calibrationNeeded": True, "message": str(error), **common, "selectedFrames": extraction["selectedFrames"] if extraction else request.get("selectedFrames")}
    manifest = {
        "version": 1, "sourceFingerprint": request["sourceFingerprint"],
        "width": image.shape[1], "height": image.shape[0],
        "patchBox": extraction["patchBox"],
        "mouths": {pose: f"mouth-{pose}.png" for pose in ("closed", "half", "open")},
        "selectedFrames": extraction["selectedFrames"],
        "manual": request.get("manual"), "correction": correction(request.get("correction")),
        "anchors": {"chin": prediction["keypoints"][2, :2].tolist()},
        **trajectory,
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    read_manifest(path)
    return {"ready": True, "manifest": "manifest.json", **common, **extraction, "frameCount": len(trajectory["track"]), "duration": trajectory["duration"]}


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if request["action"] == "inspect":
        from core.media.sprite_mouth.frames import mouth_frames
        output = Path(request["output"])
        _, previews = mouth_frames(output / "speech.mp4", output / "frames")
        timing = json.loads((output / "frames.json").read_text(encoding="utf-8"))
        emit("result", result={"frames": previews, "speechFps": timing["fps"], "speechVideo": "speech.mp4"})
        return
    detector, device = None, "manual"
    if not request.get("manual") or (request["action"] == "analyze" and request.get("selectedFrames") is None):
        from core.media.sprite_mouth.detector import load_detector
        emit("progress", message="正在加载口型识别模型")
        detector, device = load_detector(request["models"], request.get("device", "auto"))
    if request["action"] == "prepare":
        result = prepare(request, detector)
    elif request["action"] == "analyze":
        result = analyze(request, detector, device)
    elif request["action"] == "transfer":
        from core.media.sprite_mouth.transfer import transfer
        result = transfer(request, detector, lambda message: emit("progress", message=message))
    else:
        raise ValueError("未知口型处理操作")
    emit("result", result=result)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        emit("error", message=str(error))
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)

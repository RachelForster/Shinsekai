import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from application.characters import mouth_sync
from core.sprite.transitions import sprite_fingerprint

MANUAL = {"mouthBox": [.4, .35, .6, .48], "chin": [.5, .55]}
SELECTED = {"closed": 0, "half": 1, "open": 2}


def test_complete_manual_anchors_do_not_call_or_require_a_detector():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from core.media.sprite_mouth.detector import detect

    detector = Mock(side_effect=AssertionError("manual placement must not run recognition"))
    prediction = detect(detector, np.zeros((120, 80, 3), dtype=np.uint8), manual=MANUAL)
    detector.assert_not_called()
    assert prediction["keypoints"][2, :2].tolist() == pytest.approx([40, 66])
    assert prediction["keypoints"][24, 0] == pytest.approx(32)


def test_manual_pipeline_works_with_no_detectable_face_and_records_frame_timing(tmp_path):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from core.media.sprite_mouth import worker
    from core.media.sprite_mouth.manifest import read_manifest

    reference = tmp_path / "input.png"
    Image.new("RGB", (80, 120), "white").save(reference)
    original_crop = [10, 12, 70, 100]
    detector = Mock(side_effect=AssertionError("manual selection must not run recognition"))
    prepared = worker.prepare({"reference": str(reference), "output": str(tmp_path), "manual": MANUAL, "speechCrop": original_crop}, detector)
    assert prepared["speechCrop"] == original_crop
    assert prepared["suggestedManual"] == MANUAL
    with av.open(str(tmp_path / "speech.mp4"), "w") as container:
        stream = container.add_stream("mpeg4", rate=24)
        stream.width, stream.height, stream.pix_fmt = 64, 96, "yuv420p"
        for index in range(5):
            image = np.full((96, 64, 3), [80 + index * 20, 100, 130], dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(image, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    result = worker.analyze({"output": str(tmp_path), "manual": MANUAL, "selectedFrames": SELECTED, "sourceFingerprint": sprite_fingerprint(reference)}, detector, "manual")
    assert result["ready"] and result["selectedFrames"] == SELECTED
    assert result["speechFps"] == 24
    assert result["frames"][1]["time"] == pytest.approx(1 / 24)
    assert result["manual"] == MANUAL
    detector.assert_not_called()
    assert read_manifest(tmp_path / "manifest.json")["manual"] == MANUAL
    assert json.loads((tmp_path / "frames.json").read_text())["fps"] == 24


def test_manual_preparation_keeps_automatic_face_anchors_separate_from_hand_placed_chin(tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    pytest.importorskip("av")
    from core.media.sprite_mouth import worker
    from core.media.sprite_mouth.geometry import manual_prediction

    reference = tmp_path / "input.png"
    Image.new("RGB", (80, 120), "white").save(reference)
    detected = manual_prediction(MANUAL, 80, 120)["keypoints"]
    detected[11:24, 2] = .9
    changed = {**MANUAL, "chin": [.52, .57]}
    detector = Mock(side_effect=AssertionError("cached anchors should be reused"))
    prepared = worker.prepare(
        {"reference": str(reference), "output": str(tmp_path), "manual": changed, "trackingKeypoints": detected.tolist()},
        detector,
    )
    assert prepared["trackingKeypoints"] == detected.tolist()
    assert np.asarray(prepared["keypoints"])[2, :2] == pytest.approx([41.6, 68.4])
    detector.assert_not_called()


def test_head_motion_ignores_an_unreliable_eye_and_rejects_a_slipped_match():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    pytest.importorskip("av")
    from core.media.sprite_mouth.geometry import transform
    from core.media.sprite_mouth.tracking import _face_motion

    anchors = np.array([[30., 30.], [90., 30.], [60., 45.]])
    truth = np.array([[.99, .08, -1.], [-.08, .99, 7.]])
    offsets = transform(anchors, truth) - anchors
    offsets[0] = [14, 15]
    motion, _ = _face_motion(anchors, offsets, np.array([.1, .9, .95]), 60.)
    assert motion == pytest.approx(truth)
    offsets = np.array([[14., 15.], [1., 3.], [1., 3.]])
    motion, _ = _face_motion(anchors, offsets, np.array([.88, .9, .95]), 60.)
    assert motion == pytest.approx(np.array([[1., 0., 1.], [0., 1., 3.]]))


def test_applying_frames_does_not_require_landmarks_in_unselected_frames(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from core.media.sprite_mouth import extraction
    from core.media.sprite_mouth.geometry import manual_prediction

    prediction = manual_prediction(MANUAL, 80, 120)
    images = [np.full((120, 80, 3), index, dtype=np.uint8) for index in range(5)]
    selected = {"closed": 4, "half": 0, "open": 2}
    inspected = []

    def detect(_detector, image, *, boxes=None, mouth=True, chin=True):
        index = int(image[0, 0, 0])
        inspected.append(index)
        assert index in selected.values()
        if index == 2 and mouth:
            raise ValueError("unreliable lip landmarks")
        return prediction

    monkeypatch.setattr(extraction, "detect", detect)
    result = extraction.extract(None, images, images[0], prediction, [0, 0, 80, 120], tmp_path, selected=selected)
    assert inspected == [0, 2, 2, 4]
    assert result["selectedFrames"] == selected
    assert all((tmp_path / f"mouth-{pose}.png").is_file() for pose in selected)


def test_preparation_failure_retains_existing_clip_frames_and_manual_choices(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 120)).save(source)
    previous = tmp_path / "previous"
    previous.mkdir()
    (previous / "speech.mp4").write_bytes(b"existing video")
    original_crop = [5, 10, 70, 100]
    (previous / "prepared.json").write_text(json.dumps({"crop": original_crop}))
    inspect = {"speechVideo": "speech.mp4", "speechFps": 24, "frames": [{"index": 0, "time": 0, "path": "frames/000.jpg"}]}
    worker = Mock(side_effect=[ValueError("recognition failed"), inspect])
    renderer = Mock(side_effect=AssertionError("existing clip must not be generated again"))
    monkeypatch.setattr(mouth_sync, "invoke_worker", worker)
    monkeypatch.setattr(mouth_sync, "render_sprite", renderer)
    result = mouth_sync.build_bundle(tmp_path, None, source, source, tmp_path / "retry", sprite_fingerprint(source), {"name": "Mika", "manual": MANUAL, "selectedFrames": SELECTED}, Mock(), previous=previous)
    assert not result["ready"]
    assert Path(result["frames"][0]["path"]).name == "000.jpg"
    assert result["manual"] == MANUAL and result["selectedFrames"] == SELECTED
    assert worker.call_args_list[0].args[2]["speechCrop"] == original_crop
    assert worker.call_args_list[1].args[2]["action"] == "inspect"
    assert (tmp_path / "retry/speech.mp4").read_bytes() == b"existing video"
    renderer.assert_not_called()

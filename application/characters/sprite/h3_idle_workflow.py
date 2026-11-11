"""Keep idle animation close to its reference using H3's native image guides."""

from copy import deepcopy

IDLE_FRAME_COUNT = 73
SPEAKING_FRAME_COUNT = 56
ANIMATION_FPS = 24


def stabilize_idle_workflow(workflow, *, frame_count=None, anchor_pose=True):
    prepared = deepcopy(workflow)
    next_id = max((int(key) for key in prepared if str(key).isdecimal()), default=0) + 1
    for source_id, node in list(prepared.items()):
        if node.get("class_type") != "MiniMaxH3ImageToVideo":
            continue
        inputs = node["inputs"]
        length = inputs.get("length", 124)
        if isinstance(length, bool) or not isinstance(length, int) or length < 5:
            raise ValueError(
                "请在 H3 API 工作流中用至少为 5 的整数配置 length，以稳定待机姿态"
            )
        reference, vae = inputs.get("first_frame"), inputs.get("vae")
        if not all(
            isinstance(link, list) and len(link) == 2 for link in (reference, vae)
        ):
            raise ValueError("H3 稳定待机姿态需要连接 first_frame 参考图与 vae")
        # Native H3 rounds up to 17k + 5 frames. Keep both anchors inside that clip.
        original_frames = length + (5 - length) % 17
        frames = frame_count if frame_count is not None else original_frames
        if frame_count is not None:
            inputs["length"] = frames
            # Preserve custom guide timing relative to the shortened clip.
            for guide in prepared.values():
                values = guide.get("inputs", {})
                if (
                    guide.get("class_type") == "MiniMaxH3AddGuide"
                    and values.get("latent") == [source_id, 1]
                ):
                    index = values.get("frame_idx")
                    if isinstance(index, bool) or not isinstance(index, int):
                        raise ValueError("缩短动态立绘需要工作流中的 frame_idx 为整数")
                    values["frame_idx"] = round(
                        max(0, min(index, original_frames - 1))
                        * (frames - 1) / (original_frames - 1)
                    )
        if not anchor_pose:
            # First/last frames already close the loop. Repeating the still inside
            # a speaking clip repeatedly shuts the mouth and arrests body accents.
            continue
        positive = [source_id, 0]
        consumers = [
            (other["inputs"], field)
            for other_id, other in prepared.items()
            if other_id != source_id
            for field, value in other.get("inputs", {}).items()
            if value == positive
        ]
        # Keep the central motion uninterrupted; reinforce the resting pose near the ends.
        frame_indices = sorted(
            {frames // 10, frames * 9 // 10} - {0, frames - 1}
        )
        for frame_index in frame_indices:
            guide_id = str(next_id)
            next_id += 1
            prepared[guide_id] = {
                "class_type": "MiniMaxH3AddGuide",
                "inputs": {
                    "positive": positive,
                    "latent": [source_id, 1],
                    "vae": deepcopy(vae),
                    "image": deepcopy(reference),
                    "frame_idx": frame_index,
                },
            }
            positive = [guide_id, 0]
        for consumer, field in consumers:
            consumer[field] = positive.copy()
    return prepared

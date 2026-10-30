"""Keep idle animation close to its reference using H3's native image guides."""

from copy import deepcopy


def stabilize_idle_workflow(workflow):
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
        frame_count = length + (5 - length) % 17
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
            {frame_count // 10, frame_count * 9 // 10} - {0, frame_count - 1}
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

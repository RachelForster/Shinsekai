import os
import sys
from io import BytesIO
from pathlib import Path

if __package__ in {None, ""}:
    _source_root = Path(__file__).resolve().parent.parent
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from pydub import AudioSegment
from pyannote.audio import Pipeline
import torchaudio

from config.config_manager import ConfigManager
from core.file_transactions import (
    atomic_binary_writer,
    capture_directory_identity,
    read_bytes_without_links,
)
from core.process_launch import capture_launch_file, require_launch_file
from core.paths import (
    managed_child_path,
    project_root,
    require_directory_without_links,
    resolve_project_output_path,
    resolve_runtime_asset_read_path,
    safe_path_component_with_suffix,
)

config = ConfigManager()

HUGGING_FACE_TOKEN = config.config.api_config.hugging_face_access_token

def diarize_and_stitch_by_speaker(input_audio_path, output_dir):
    """
    执行说话人识别并将每个说话人的音频片段拼接起来。

    Args:
        input_audio_path (str): 输入音频文件的路径。
        output_dir (str): 输出拼接后音频文件的目录。
    """
    
    root = project_root()
    source = resolve_runtime_asset_read_path(
        os.fspath(input_audio_path),
        root=root,
    )
    if not source.is_file():
        raise FileNotFoundError(source)
    source_snapshot = capture_launch_file(
        source,
        field="diarization input audio",
    )
    output_path = resolve_project_output_path(os.fspath(output_dir), root=root)
    output_path.mkdir(parents=True, exist_ok=True)
    output_path = require_directory_without_links(
        output_path,
        field="diarization output directory",
    )
    output_path, output_identity = capture_directory_identity(
        output_path,
        field="diarization output directory",
    )
    print(f"输出目录: {output_path}")

    # 1. 初始化说话人识别 Pipeline
    try:
        print("正在加载说话人识别模型...")
        # 使用最新的说话人识别模型
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=HUGGING_FACE_TOKEN
        )
        print("模型加载完成。")
    except Exception as e:
        print("--- 错误 ---")
        print(f"加载 pyannote 模型失败，请检查您的 HUGGING_FACE_TOKEN 和网络连接。\n错误信息: {e}")
        return

    # 2. 从同一个经过校验的文件描述符加载音频，后续识别与切片都使用
    # 这一份内存数据，避免路径在多个库各自打开之间被替换。
    print(f"正在处理音频文件: {source}")
    try:
        source_payload = read_bytes_without_links(
            source_snapshot.path,
            expected_identity=source_snapshot.identity,
            expected_parent_identity=source_snapshot.parent.identity,
        )
        waveform, sample_rate = torchaudio.load(BytesIO(source_payload))
        full_audio = AudioSegment.from_file(
            BytesIO(source_payload),
            format=source.suffix.removeprefix(".") or None,
        )
        require_launch_file(source_snapshot)
        diarization = pipeline(
            {
                "waveform": waveform,
                "sample_rate": sample_rate,
            }
        )
    except Exception as e:
        print(f"说话人识别失败: {e}")
        return

    # 3. 按说话人分组片段
    speaker_segments = {}

    # 遍历识别结果
    for segment, _, speaker in diarization.itertracks(yield_labelling=True):
        start_time_sec = segment.start
        end_time_sec = segment.end
        
        # 将秒转换为毫秒，用于 pydub
        start_ms = int(start_time_sec * 1000)
        end_ms = int(end_time_sec * 1000)

        # pyannote 使用秒，而我们需要用 pydub 来处理
        # 简单起见，我们先用 pydub 加载整个音频，然后切片
        # 实际生产环境中，为了精度和效率，可能需要更底层操作
        
        if speaker not in speaker_segments:
            # 初始化一个空的 AudioSegment，代表该说话人拼接后的总音频
            speaker_segments[speaker] = AudioSegment.empty()

        # 切割并拼接这一说话人的片段。
        speaker_segments[speaker] += full_audio[start_ms:end_ms]

    # 4. 导出结果
    print("\n--- 导出结果 ---")
    if not speaker_segments:
        print("未识别到任何说话人片段。")
        return

    for speaker, stitched_audio in speaker_segments.items():
        output_filename = safe_path_component_with_suffix(
            str(speaker),
            "_stitched.wav",
            field="speaker output filename",
        )
        output_file = managed_child_path(
            output_path,
            output_filename,
            field="speaker output filename",
        )
        
        # 导出为 WAV 格式
        with atomic_binary_writer(
            output_file,
            expected_parent_identity=output_identity,
        ) as output:
            stitched_audio.export(output, format="wav")
        print(f"成功导出 {speaker} 的音频到: {output_file}")

# --- 运行示例 ---
if __name__ == "__main__":
    # 假设您的输入文件名为 'input.wav' 放在当前目录下
    # 请替换为您实际的音频文件路径，例如 'path/to/my/recording.mp3'
    INPUT_FILE = "input.wav" 
    OUTPUT_FOLDER = "output_stitched_audio"


    if HUGGING_FACE_TOKEN == "YOUR_HUGGING_FACE_TOKEN_HERE":
        print("!!! 请在代码顶部设置您的 HUGGING_FACE_TOKEN 才能运行 !!!")
    elif not resolve_runtime_asset_read_path(
        INPUT_FILE,
        root=project_root(),
    ).is_file():
        print(f"!!! 错误: 找不到输入文件 '{INPUT_FILE}'。请将您的音频文件放置于此或修改 INPUT_FILE 变量。")
    else:
        diarize_and_stitch_by_speaker(INPUT_FILE, OUTPUT_FOLDER)

import os
import numpy as np
from pydub import AudioSegment
from pyannote.audio import Pipeline
import torchaudio

from config.config_manager import ConfigManager

config = ConfigManager()

HUGGING_FACE_TOKEN = config.config.api_config.hugging_face_access_token

def diarize_and_stitch_by_speaker(input_audio_path, output_dir):
    """
    执行说话人识别并将每个说话人的音频片段拼接起来。

    Args:
        input_audio_path (str): 输入音频文件的路径。
        output_dir (str): 输出拼接后音频文件的目录。
    """
    
    # 检查输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建输出目录: {output_dir}")

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

    # 2. 执行说话人识别
    print(f"正在处理音频文件: {input_audio_path}")
    try:
        diarization = pipeline(input_audio_path)
    except Exception as e:
        print(f"说话人识别失败: {e}")
        return

    # 3. 按说话人分组片段
    speaker_segments = {}
    
    # torchaudio 读取音频用于片段提取
    waveform, sample_rate = torchaudio.load(input_audio_path)
    # 将 waveform 转换为 numpy 数组以便处理
    waveform_np = waveform.squeeze().numpy() 

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

        try:
            # 使用 pydub 加载整个音频（确保格式兼容，如wav, mp3）
            full_audio = AudioSegment.from_file(input_audio_path)
            # 切割出该片段
            segment_audio = full_audio[start_ms:end_ms]
            
            # 拼接片段
            speaker_segments[speaker] += segment_audio
        
        except Exception as e:
            print(f"处理说话人 {speaker} 的片段时出错: {e}")
            continue

    # 4. 导出结果
    print("\n--- 导出结果 ---")
    if not speaker_segments:
        print("未识别到任何说话人片段。")
        return

    for speaker, stitched_audio in speaker_segments.items():
        output_filename = os.path.join(output_dir, f"{speaker}_stitched.wav")
        
        # 导出为 WAV 格式
        stitched_audio.export(output_filename, format="wav")
        print(f"成功导出 {speaker} 的音频到: {output_filename}")

# --- 运行示例 ---
if __name__ == "__main__":
    # 假设您的输入文件名为 'input.wav' 放在当前目录下
    # 请替换为您实际的音频文件路径，例如 'path/to/my/recording.mp3'
    INPUT_FILE = "input.wav" 
    OUTPUT_FOLDER = "output_stitched_audio"


    if HUGGING_FACE_TOKEN == "YOUR_HUGGING_FACE_TOKEN_HERE":
        print("!!! 请在代码顶部设置您的 HUGGING_FACE_TOKEN 才能运行 !!!")
    elif not os.path.exists(INPUT_FILE):
        print(f"!!! 错误: 找不到输入文件 '{INPUT_FILE}'。请将您的音频文件放置于此或修改 INPUT_FILE 变量。")
    else:
        diarize_and_stitch_by_speaker(INPUT_FILE, OUTPUT_FOLDER)